from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Dict, Optional

from database import postgres as db

logger = logging.getLogger(__name__)

_GENERIC_CITY_FOLDER_NAMES = {
    "input",
    "inputs",
    "data",
    "datasets",
    "dataset",
    "csv",
    "csvs",
    "mount",
    "mnt",
}


def _parse_city_from_folder_name(name: str) -> Optional[str]:
    m = re.match(r"^\d+([^_]+)_", name)
    if m:
        return m.group(1)

    m = re.match(r"^\d+([A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff-]*)$", name)
    if m:
        return m.group(1)

    return None


def _parse_city_from_csv_stem(csv_stem: str) -> Optional[str]:
    if "_" not in csv_stem:
        return None

    suffix = csv_stem.rsplit("_", 1)[-1].strip()
    if not suffix or suffix.isdigit():
        return None

    if re.fullmatch(r"[A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff-]*", suffix):
        return suffix

    return None


def _derive_city_name(csv_path_dir: Path, csv_paths: list[Path], city_name: Optional[str] = None) -> str:
    if city_name and city_name.strip():
        return city_name.strip()

    parsed_root_city = _parse_city_from_folder_name(csv_path_dir.name)
    if parsed_root_city:
        return parsed_root_city

    if csv_path_dir.name.lower() not in _GENERIC_CITY_FOLDER_NAMES:
        return csv_path_dir.name

    for csv_path in csv_paths:
        try:
            relative_parts = csv_path.relative_to(csv_path_dir).parts[:-1]
        except ValueError:
            relative_parts = csv_path.parts[:-1]

        for part in relative_parts:
            parsed_part_city = _parse_city_from_folder_name(part)
            if parsed_part_city:
                return parsed_part_city

        parsed_stem_city = _parse_city_from_csv_stem(csv_path.stem)
        if parsed_stem_city:
            return parsed_stem_city

    return csv_path_dir.name


def _resolve_park_image_dirs(
    csv_path: Path,
    csv_path_dir: Path,
    images_root: Optional[Path],
    csv_stem: str,
    park_label: str,
) -> list[Path]:
    """Return candidate directories that may contain images for one park CSV.

    Supports layouts where images are in:
    - a direct park folder: ``park1/``
    - split class folders as siblings: ``park1-class0/``, ``park1-class1/``
    - class folders under park folder: ``park1/class0/``
    """
    if images_root:
        try:
            rel_parent = csv_path.parent.relative_to(csv_path_dir)
        except ValueError:
            rel_parent = Path(".")
        base_dirs = [Path(images_root) / rel_parent, Path(images_root)]
    else:
        base_dirs = [csv_path.parent, csv_path_dir]

    park_names = [csv_stem, park_label]
    resolved: list[Path] = []
    seen: set[Path] = set()

    for base in base_dirs:
        if not base.exists() or not base.is_dir():
            continue

        for park_name in park_names:
            # Direct park directory (images may be directly inside or in nested class dirs)
            direct = base / park_name
            if direct.is_dir() and direct not in seen:
                seen.add(direct)
                resolved.append(direct)

            # Split sibling directories, e.g. park1-class0 / park1_class1 / park1 class2
            for pattern in (f"{park_name}-class*", f"{park_name}_class*", f"{park_name} class*"):
                for d in sorted(base.glob(pattern)):
                    if d.is_dir() and d not in seen:
                        seen.add(d)
                        resolved.append(d)

    return resolved


def _build_park_image_lookup(self, park_dirs: list[Path]) -> Dict[str, Path]:
    """Merge filename->path lookups from all matched park directories."""
    lookup: Dict[str, Path] = {}
    for d in park_dirs:
        for name, p in type(self)._build_image_lookup(d).items():
            lookup.setdefault(name, p)
    return lookup


def _log_progress_milestone(current: int, total: int, *, label: str, step: int = 10) -> None:
    if current <= 0:
        return
    if current % step == 0 or current == total:
        logger.info("%s progress: %d/%d ready", label, current, total)


def _normalize_ingestion_status_key(path_like: Path | str) -> str:
    """Normalize status keys, stripping generic mount roots like /input.

    Examples:
    - /input/36Chengdu/a.csv -> /36Chengdu/a.csv
    - input/36Chengdu -> /36Chengdu
    - plain.csv -> plain.csv
    """
    original = str(path_like)
    s = original.strip().replace("\\", "/")
    if not s:
        return s

    # Keep Windows absolute paths untouched to avoid rewriting local dev paths.
    if re.match(r"^[A-Za-z]:/", s):
        return original

    parts = [p for p in s.split("/") if p and p != "."]
    if not parts:
        return "/" if s.startswith("/") else s

    if parts[0].lower() in _GENERIC_CITY_FOLDER_NAMES and len(parts) > 1:
        parts = parts[1:]

    if "/" not in s and len(parts) == 1 and parts[0] == s:
        return s

    return "/" + "/".join(parts)


def _csv_status_key(csv_path: Path, csv_path_dir: Path) -> str:
    """Build a stable key under city scope instead of mount scope."""
    try:
        rel = csv_path.relative_to(csv_path_dir.parent)
    except ValueError:
        try:
            rel = csv_path.relative_to(csv_path_dir)
        except ValueError:
            rel = csv_path
    return _normalize_ingestion_status_key(rel)


def ingest_posts_impl(
    self,
    csv_folder: Path,
    images_root: Optional[Path] = None,
    max_posts: Optional[int] = None,
    city_name: Optional[str] = None,
    debug: bool = False,
) -> int:
    # reuse original orchestrator implementation but as a function to reduce file size
    csv_path_dir = Path(csv_folder)
    if not csv_path_dir.is_dir():
        raise FileNotFoundError(f"CSV folder not found: {csv_path_dir}")

    count = 0
    image_count = 0
    csv_count = 0
    use_json = bool(self.output_json)

    csv_paths = sorted(
        p for p in csv_path_dir.rglob("*") if p.is_file() and p.suffix.lower() == ".csv"
    )
    city_name = _derive_city_name(csv_path_dir, csv_paths, city_name=city_name)
    total_csv = len(csv_paths)
    logger.info("Found %d CSV files to process in %s (recursive)", total_csv, csv_path_dir)

    # Delegate to the instance's methods/attributes as needed
    if not use_json:
        with db.connect(self.dsn) as conn:
            db.ensure_schema(conn)
            for file_idx, csv_path in enumerate(csv_paths, start=1):
                csv_count = file_idx
                status_key = _csv_status_key(csv_path, csv_path_dir)
                prev = db.get_ingestion_status(conn, status_key)
                if prev is not None and prev[2] == "done":
                    logger.info("skipping already-done CSV %s (%d/%d)", csv_path, csv_count, total_csv)
                    continue

                logger.info("ingesting CSV %s (%d/%d)", csv_path, csv_count, total_csv)
                db.upsert_ingestion_status(conn, filename=status_key, status="processing", last_processed_row=0)

                csv_stem = csv_path.stem
                mpark = re.match(r'^(?:\d+_)*(.+)', csv_stem)
                park_label = mpark.group(1) if mpark else csv_stem

                park_dirs = _resolve_park_image_dirs(
                    csv_path=csv_path,
                    csv_path_dir=csv_path_dir,
                    images_root=images_root,
                    csv_stem=csv_stem,
                    park_label=park_label,
                )
                image_lookup: Dict[str, Path] = _build_park_image_lookup(self, park_dirs)

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
                            db.upsert_ingestion_status(conn, filename=status_key, status="done", last_processed_row=count)
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
                                    logger.debug("image %s not found in any matched park directory", fname)
                                    continue
                                normalized_path = _normalize_ingestion_status_key(resolved)
                                db.insert_image(conn, post_id=post_id, path=normalized_path, username_hash=h)
                                image_count += 1
                        else:
                            if image_lookup:
                                matched = []
                                for name, p in image_lookup.items():
                                    if name.startswith(username) or name.startswith(username + "_") or name.startswith(username + "-") or username in name:
                                        matched.append(p)
                                for p in matched:
                                    normalized_path = _normalize_ingestion_status_key(p)
                                    db.insert_image(conn, post_id=post_id, path=normalized_path, username_hash=h)
                                    image_count += 1

                        db.upsert_ingestion_status(conn, filename=status_key, status="processing", last_processed_row=idx)

                db.upsert_ingestion_status(conn, filename=status_key, status="done", last_processed_row=count)
                logger.info("completed CSV %s (%d/%d)", csv_path, csv_count, total_csv)

            if csv_paths:
                logger.info("CSV ingestion progress: %d/%d files ready", csv_count, total_csv)
    else:
        # JSON mode
        for file_idx, csv_path in enumerate(csv_paths, start=1):
            csv_count = file_idx
            status_key = _csv_status_key(csv_path, csv_path_dir)

            prev = next((s for s in self._json_store["ingestion_status"] if s.get("filename") == status_key), None)
            if prev is not None and prev.get("status") == "done":
                logger.info("skipping already-done CSV %s (%d/%d)", csv_path, csv_count, total_csv)
                continue
            logger.info("ingesting CSV %s (%d/%d)", csv_path, csv_count, total_csv)
            self._json_store["ingestion_status"].append({"filename": status_key, "status": "processing", "last_processed_row": 0})

            csv_stem = csv_path.stem
            mpark = re.match(r'^(?:\d+_)*(.+)', csv_stem)
            park_label = mpark.group(1) if mpark else csv_stem

            park_dirs = _resolve_park_image_dirs(
                csv_path=csv_path,
                csv_path_dir=csv_path_dir,
                images_root=images_root,
                csv_stem=csv_stem,
                park_label=park_label,
            )
            image_lookup: Dict[str, Path] = _build_park_image_lookup(self, park_dirs)

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
                            if s.get("filename") == status_key:
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
                                logger.debug("image %s not found in any matched park directory", fname)
                                continue
                            image_id = self._next_image_id
                            self._next_image_id += 1
                            normalized_path = _normalize_ingestion_status_key(resolved)
                            self._json_store["images"].append({"id": image_id, "post_id": post_id, "path": normalized_path, "username_hash": h})
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
                                normalized_path = _normalize_ingestion_status_key(p)
                                self._json_store["images"].append({"id": image_id, "post_id": post_id, "path": normalized_path, "username_hash": h})
                                image_count += 1

                    for s in self._json_store.get("ingestion_status", []):
                        if s.get("filename") == status_key:
                            s["last_processed_row"] = idx
                            break

            for s in self._json_store.get("ingestion_status", []):
                if s.get("filename") == status_key:
                    s["status"] = "done"
                    s["last_processed_row"] = count
                    break
            logger.info("completed CSV %s (%d/%d)", csv_path, csv_count, total_csv)
        if csv_paths:
            logger.info("CSV ingestion progress: %d/%d files ready", csv_count, total_csv)
    logger.info("All CSV files processed: %d/%d; ingested %d posts and %d images from %s", csv_count, total_csv, count, image_count, csv_path_dir)

    if debug:
        self.print_sample_posts(limit=5)

    return count


def ingest_images_impl(self, folders, image_storage: Optional[Path] = None) -> int:
    # Images are analyzed from their original source paths, so we no longer
    # copy files into a separate storage folder.

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

            for folder_idx, (folder, paths) in enumerate(folder_paths_list, start=1):
                status_key = _normalize_ingestion_status_key(folder)
                prev = db.get_ingestion_status(conn, status_key)
                if prev is not None and prev[2] == "done":
                    logger.info("skipping already-done image folder %s", folder)
                    continue

                logger.info("scanning images in %s (found %d)", folder, len(paths))
                db.upsert_ingestion_status(conn, filename=status_key, status="processing")

                for path in paths:
                    if db.image_path_exists(conn, str(path)):
                        logger.debug("skipping already-ingested image %s", path)
                        processed += 1
                        continue

                    stem = path.stem
                    username_hash = stem.split("_")[0] if "_" in stem else None
                    try:
                        normalized_path = _normalize_ingestion_status_key(path)
                        image_id = db.insert_image(
                            conn,
                            post_id=None,
                            path=normalized_path,
                            username_hash=username_hash,
                        )
                    except Exception:
                        logger.exception("failed to insert image %s", path)
                        continue
                    _ = image_id
                    inserted += 1
                    processed += 1
                    _log_progress_milestone(processed, total_images, label="Image ingestion")

                db.upsert_ingestion_status(conn, filename=status_key, status="done")
                logger.info("completed image folder %s (%d/%d)", folder, folder_idx, len(folder_paths_list))
    else:
        for folder_idx, (folder, paths) in enumerate(folder_paths_list, start=1):
            status_key = _normalize_ingestion_status_key(folder)
            prev = next((s for s in self._json_store["ingestion_status"] if s.get("filename") == status_key), None)
            if prev is not None and prev.get("status") == "done":
                logger.info("skipping already-done image folder %s", folder)
                continue

            logger.info("scanning images in %s (found %d)", folder, len(paths))
            self._json_store.setdefault("ingestion_status", []).append({"filename": status_key, "status": "processing", "last_processed_row": 0})

            for path in paths:
                if any(p.get("path") == str(path) for p in self._json_store.get("images", [])):
                    logger.debug("skipping already-ingested image %s", path)
                    processed += 1
                    continue

                stem = path.stem
                username_hash = stem.split("_")[0] if "_" in stem else None
                image_id = self._next_image_id
                self._next_image_id += 1
                normalized_path = _normalize_ingestion_status_key(path)
                self._json_store.setdefault("images", []).append({"id": image_id, "post_id": None, "path": normalized_path, "username_hash": username_hash})
                inserted += 1
                processed += 1
                _log_progress_milestone(processed, total_images, label="Image ingestion")

            for s in self._json_store.get("ingestion_status", []):
                if s.get("filename") == status_key:
                    s["status"] = "done"
                    break
            logger.info("completed image folder %s (%d/%d)", folder, folder_idx, len(folder_paths_list))

    folder_summary = ", ".join(str(f) for f in folders) if isinstance(folders, list) else str(folders)
    logger.info("All image folders processed: %d/%d scanned; inserted %d/%d images from %s", len(folder_paths_list), len(folder_paths_list), inserted, total_images, folder_summary)
    return inserted
