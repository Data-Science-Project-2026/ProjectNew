from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Dict, Optional

from database import postgres as db

logger = logging.getLogger(__name__)


def ingest_posts_impl(self, csv_folder: Path, images_root: Optional[Path] = None, max_posts: Optional[int] = None, debug: bool = False) -> int:
    # reuse original orchestrator implementation but as a function to reduce file size
    csv_path_dir = Path(csv_folder)
    if not csv_path_dir.is_dir():
        raise FileNotFoundError(f"CSV folder not found: {csv_path_dir}")

    m = re.match(r"^\d+([^_]+)_", csv_path_dir.name)
    if m:
        city_name = m.group(1)
    else:
        m2 = re.match(r"^\d+(.+)", csv_path_dir.name)
        city_name = m2.group(1) if m2 else csv_path_dir.name

    count = 0
    image_count = 0
    csv_count = 0
    use_json = bool(self.output_json)

    csv_paths = sorted(csv_path_dir.glob("*.csv"))
    total_csv = len(csv_paths)
    logger.info("Found %d CSV files to process in %s", total_csv, csv_path_dir)

    # Delegate to the instance's methods/attributes as needed
    if not use_json:
        with db.connect(self.dsn) as conn:
            db.ensure_schema(conn)
            for file_idx, csv_path in enumerate(csv_paths, start=1):
                csv_count = file_idx
                prev = db.get_ingestion_status(conn, str(csv_path))
                if prev is not None and prev[2] == "done":
                    logger.info("skipping already-done CSV %s (%d/%d)", csv_path, csv_count, total_csv)
                    continue

                logger.info("ingesting CSV %s (%d/%d)", csv_path, csv_count, total_csv)
                db.upsert_ingestion_status(conn, filename=str(csv_path), status="processing", last_processed_row=0)

                csv_stem = csv_path.stem
                mpark = re.match(r'^(?:\d+_)*(.+)', csv_stem)
                park_label = mpark.group(1) if mpark else csv_stem

                if images_root:
                    park_dir = Path(images_root) / csv_stem
                    if not park_dir.is_dir():
                        park_dir = Path(images_root) / park_label
                else:
                    park_dir = csv_path_dir / csv_stem
                    if not park_dir.is_dir():
                        park_dir = csv_path_dir / park_label

                image_lookup: Dict[str, Path] = {}
                if park_dir.is_dir():
                    image_lookup = type(self)._build_image_lookup(park_dir)

                with open(csv_path, newline="", encoding="utf-8-sig") as fh:
                    reader = csv.DictReader(fh)
                    fieldnames = reader.fieldnames or []
                    normalized_fields = {f.strip().lower() for f in fieldnames}
                    has_image_column = any(n in normalized_fields for n in ("图像文件名列表", "image", "images", "图像", "image_filenames", "filenames"))

                    def _get(r: dict, *keys: str) -> str:
                        for k in keys:
                            v = r.get(k)
                            if v is not None and str(v).strip() != "":
                                return str(v).strip()
                        return ""

                    for idx, row in enumerate(reader, start=1):
                        if max_posts and count >= max_posts:
                            db.upsert_ingestion_status(conn, filename=str(csv_path), status="done", last_processed_row=count)
                            logger.info("processed %d/%d CSV files before reaching max_posts; ingested %d posts and %d images from %s", csv_count, total_csv, count, image_count, csv_path_dir)
                            return count

                        username = _get(row, "用户名", "原始用户名", "username", "user", "user_name", "name", "昵称")
                        if not username:
                            continue
                        h = hashlib.sha256(username.encode("utf-8")).hexdigest()

                        comment = _get(row, "评论", "text", "comment", "内容") or None
                        raw_time = _get(row, "时间", "timestamp", "time", "date", "日期")
                        timestamp = None
                        if raw_time:
                            m = re.search(r"\d{4}-\d{1,2}-\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?", raw_time)
                            if m:
                                timestamp = m.group(0)
                            else:
                                m2 = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", raw_time)
                                if m2:
                                    y, mo, da = m2.group(1), int(m2.group(2)), int(m2.group(3))
                                    timestamp = f"{y}-{mo:02d}-{da:02d}"
                        rating = _get(row, "评分", "rating", "score") or None

                        park_val = park_label

                        post_id = db.insert_post(
                            conn,
                            city=city_name,
                            park=park_val,
                            username=username,
                            username_hash=h,
                            comment=comment,
                            time=timestamp,
                            rating=rating,
                        )
                        count += 1

                        if has_image_column and image_lookup:
                            raw_images = row.get("图像文件名列表") or row.get("image") or ""
                            if not raw_images:
                                raw_images = _get(row, "图像文件名列表", "image", "images", "image_filenames", "filenames")
                            filenames = [s.strip() for s in raw_images.replace("|", ";").replace(",", ";").split(";") if s.strip()]
                            for fname in filenames:
                                resolved = image_lookup.get(Path(fname).name)
                                if resolved is None:
                                    logger.debug("image %s not found in %s", fname, park_dir)
                                    continue
                                db.insert_image(conn, post_id=post_id, path=str(resolved), username_hash=h)
                                image_count += 1
                        else:
                            if image_lookup:
                                matched = []
                                for name, p in image_lookup.items():
                                    if name.startswith(username) or name.startswith(username + "_") or name.startswith(username + "-") or username in name:
                                        matched.append(p)
                                for p in matched:
                                    db.insert_image(conn, post_id=post_id, path=str(p), username_hash=h)
                                    image_count += 1

                        db.upsert_ingestion_status(conn, filename=str(csv_path), status="processing", last_processed_row=idx)

            db.upsert_ingestion_status(conn, filename=str(csv_path), status="done", last_processed_row=count)
            if csv_count % 100 == 0:
                logger.info("progress: processed %d/%d CSV files", csv_count, total_csv)
    else:
        # JSON mode
        for file_idx, csv_path in enumerate(csv_paths, start=1):
            csv_count = file_idx

            prev = next((s for s in self._json_store["ingestion_status"] if s.get("filename") == str(csv_path)), None)
            if prev is not None and prev.get("status") == "done":
                logger.info("skipping already-done CSV %s (%d/%d)", csv_path, csv_count, total_csv)
                continue
            logger.info("ingesting CSV %s (%d/%d)", csv_path, csv_count, total_csv)
            self._json_store["ingestion_status"].append({"filename": str(csv_path), "status": "processing", "last_processed_row": 0})

            csv_stem = csv_path.stem
            mpark = re.match(r'^(?:\d+_)*(.+)', csv_stem)
            park_label = mpark.group(1) if mpark else csv_stem

            if images_root:
                park_dir = Path(images_root) / csv_stem
                if not park_dir.is_dir():
                    park_dir = Path(images_root) / park_label
            else:
                park_dir = csv_path_dir / csv_stem
                if not park_dir.is_dir():
                    park_dir = csv_path_dir / park_label

            image_lookup: Dict[str, Path] = {}
            if park_dir.is_dir():
                image_lookup = type(self)._build_image_lookup(park_dir)

            with open(csv_path, newline="", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                fieldnames = reader.fieldnames or []
                normalized_fields = {f.strip().lower() for f in fieldnames}
                has_image_column = any(n in normalized_fields for n in ("图像文件名列表", "image", "images", "图像", "image_filenames", "filenames"))

                def _get(r: dict, *keys: str) -> str:
                    for k in keys:
                        v = r.get(k)
                        if v is not None and str(v).strip() != "":
                            return str(v).strip()
                    return ""

                for idx, row in enumerate(reader, start=1):
                    if max_posts and count >= max_posts:
                        for s in self._json_store["ingestion_status"]:
                            if s.get("filename") == str(csv_path):
                                s["status"] = "done"
                                s["last_processed_row"] = count
                                break
                        logger.info("processed %d/%d CSV files before reaching max_posts; ingested %d posts and %d images from %s", csv_count, total_csv, count, image_count, csv_path_dir)
                        return count

                    username = _get(row, "用户名", "原始用户名", "username", "user", "user_name", "name", "昵称")
                    if not username:
                        continue
                    h = hashlib.sha256(username.encode("utf-8")).hexdigest()

                    comment = _get(row, "评论", "text", "comment", "内容") or None
                    raw_time = _get(row, "时间", "timestamp", "time", "date", "日期")
                    timestamp = None
                    if raw_time:
                        m = re.search(r"\d{4}-\d{1,2}-\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?", raw_time)
                        if m:
                            timestamp = m.group(0)
                        else:
                            m2 = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", raw_time)
                            if m2:
                                y, mo, da = m2.group(1), int(m2.group(2)), int(m2.group(3))
                                timestamp = f"{y}-{mo:02d}-{da:02d}"
                    rating = _get(row, "评分", "rating", "score") or None

                    park_val = park_label

                    post_id = self._next_post_id
                    self._next_post_id += 1
                    self._json_store["posts"].append({
                        "id": post_id,
                        "city": city_name,
                        "park": park_val,
                        "username": username,
                        "username_hash": h,
                        "comment": comment,
                        "time": timestamp,
                        "rating": rating,
                    })
                    count += 1

                    if has_image_column and image_lookup:
                        raw_images = row.get("图像文件名列表") or row.get("image") or ""
                        if not raw_images:
                            raw_images = _get(row, "图像文件名列表", "image", "images", "image_filenames", "filenames")
                        filenames = [s.strip() for s in raw_images.replace("|", ";").replace(",", ";").split(";") if s.strip()]
                        for fname in filenames:
                            resolved = image_lookup.get(Path(fname).name)
                            if resolved is None:
                                logger.debug("image %s not found in %s", fname, park_dir)
                                continue
                            image_id = self._next_image_id
                            self._next_image_id += 1
                            self._json_store["images"].append({"id": image_id, "post_id": post_id, "path": str(resolved), "username_hash": h})
                            image_count += 1
                    else:
                        if image_lookup:
                            matched = []
                            for name, p in image_lookup.items():
                                if name.startswith(username) or name.startswith(username + "_") or name.startswith(username + "-") or username in name:
                                    matched.append(p)
                            for p in matched:
                                image_id = self._next_image_id
                                self._next_image_id += 1
                                self._json_store["images"].append({"id": image_id, "post_id": post_id, "path": str(p), "username_hash": h})
                                image_count += 1

                    for s in self._json_store.get("ingestion_status", []):
                        if s.get("filename") == str(csv_path):
                            s["last_processed_row"] = idx
                            break

            for s in self._json_store.get("ingestion_status", []):
                if s.get("filename") == str(csv_path):
                    s["status"] = "done"
                    s["last_processed_row"] = count
                    break
            if csv_count % 100 == 0:
                logger.info("progress: processed %d/%d CSV files", csv_count, total_csv)
    logger.info("All CSV files processed: %d/%d; ingested %d posts and %d images from %s", csv_count, total_csv, count, image_count, csv_path_dir)

    if debug:
        self.print_sample_posts(limit=5)

    return count


def ingest_images_impl(self, folders, image_storage: Optional[Path] = None) -> int:
    if image_storage is None:
        image_storage = Path("data/images")
    image_storage = image_storage.resolve()
    image_storage.mkdir(parents=True, exist_ok=True)

    inserted = 0
    processed = 0
    use_json = bool(self.output_json)

    folder_paths_list = []
    total_images = 0
    for folder in folders:
        if not folder.exists():
            logger.warning("image folder does not exist: %s", folder)
            folder_paths_list.append((folder, []))
            continue
        paths = [p for p in folder.rglob("*") if p.is_file() and not p.name.startswith('.') and p.suffix.lower() not in {'.csv', '.txt'}]
        folder_paths_list.append((folder, paths))
        total_images += len(paths)

    logger.info("Found %d images to process across %d folders", total_images, len(folder_paths_list))

    if not use_json:
        with db.connect(self.dsn) as conn:
            db.ensure_schema(conn)

            for folder, paths in folder_paths_list:
                prev = db.get_ingestion_status(conn, str(folder))
                if prev is not None and prev[2] == "done":
                    logger.info("skipping already-done image folder %s", folder)
                    continue

                logger.info("scanning images in %s (found %d)", folder, len(paths))
                db.upsert_ingestion_status(conn, filename=str(folder), status="processing")

                for path in paths:
                    if db.image_path_exists(conn, str(path)):
                        logger.debug("skipping already-ingested image %s", path)
                        processed += 1
                        continue

                    stem = path.stem
                    username_hash = stem.split("_")[0] if "_" in stem else None
                    try:
                        image_id = db.insert_image(
                            conn,
                            post_id=None,
                            path=str(path),
                            username_hash=username_hash,
                        )
                    except Exception:
                        logger.exception("failed to insert image %s", path)
                        continue
                    dest = image_storage / f"{image_id}{path.suffix}"
                    try:
                        shutil.copy2(path, dest)
                    except Exception:
                        logger.exception("failed to copy image %s to %s", path, dest)
                    inserted += 1
                    processed += 1
                    if processed % 100 == 0:
                        logger.info("progress: processed %d/%d images", processed, total_images)

                db.upsert_ingestion_status(conn, filename=str(folder), status="done")
    else:
        for folder, paths in folder_paths_list:
            prev = next((s for s in self._json_store["ingestion_status"] if s.get("filename") == str(folder)), None)
            if prev is not None and prev.get("status") == "done":
                logger.info("skipping already-done image folder %s", folder)
                continue

            logger.info("scanning images in %s (found %d)", folder, len(paths))
            self._json_store.setdefault("ingestion_status", []).append({"filename": str(folder), "status": "processing", "last_processed_row": 0})

            for path in paths:
                if any(p.get("path") == str(path) for p in self._json_store.get("images", [])):
                    logger.debug("skipping already-ingested image %s", path)
                    processed += 1
                    continue

                stem = path.stem
                username_hash = stem.split("_")[0] if "_" in stem else None
                image_id = self._next_image_id
                self._next_image_id += 1
                self._json_store.setdefault("images", []).append({"id": image_id, "post_id": None, "path": str(path), "username_hash": username_hash})
                dest = image_storage / f"{image_id}{path.suffix}"
                try:
                    shutil.copy2(path, dest)
                except Exception:
                    logger.exception("failed to copy image %s to %s", path, dest)
                inserted += 1
                processed += 1
                if processed % 100 == 0:
                    logger.info("progress: processed %d/%d images", processed, total_images)

            for s in self._json_store.get("ingestion_status", []):
                if s.get("filename") == str(folder):
                    s["status"] = "done"
                    break

    logger.info("All images processed: %d/%d; inserted %d images", processed, total_images, inserted)
    return inserted
