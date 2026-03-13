from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
import base64
import shutil
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, List, Optional, Dict

from src.database import postgres as db


logger = logging.getLogger(__name__)


class Pipeline:
    """High‑level orchestrator for ingestion + analysis.

    ``Pipeline`` encapsulates every step described in ``documentation/pipeline.md``
    and makes it easy to run the full workflow from the command line or from a
    larger program.  The class is deliberately simple so that you can swap out
    individual components (e.g. a different sentiment model) without rewriting
    the orchestration logic.
    """

    def __init__(
        self,
        dsn: str,
        bio_clip_args: dict,
        bert_args: dict | None = None,
        qwen_args: dict | None = None,
        *,
        bio_service_url: Optional[str] = None,
        bert_service_url: Optional[str] = None,
        qwen_service_url: Optional[str] = None,
        skip_bio: bool = False,
        skip_bert: bool = False,
        skip_qwen: bool = False,
    ) -> None:
        self.dsn = dsn
        # if service urls provided we avoid loading local models until
        # the caller explicitly needs them.  skip_* flags allow tests where a
        # model should be omitted entirely (e.g. qwen-only runs).
        self.bio_service_url = bio_service_url
        self.bert_service_url = bert_service_url
        self.qwen_service_url = qwen_service_url
        self.skip_bio = skip_bio
        self.skip_bert = skip_bert
        self.skip_qwen = skip_qwen
        self.bio_clip_args = dict(bio_clip_args)
        self.bert_args = dict(bert_args or {})

        # local model instances are now loaded on first use so commands like
        # upload-posts do not require BioClip/Bert dependencies.
        self.bio = None
        self.bert = None
        self.qwen_args = qwen_args or {}
        
        # New Qwen configuration mapping
        self.qwen_image_model = self.qwen_args.get("image_model", "Qwen/Qwen3.5-4B")
        self.qwen_text_model = self.qwen_args.get("text_model", "Qwen/Qwen3.5-4B")
        self.qwen_image_instruction_file = self.qwen_args.get("image_instruction_file")
        self.qwen_comment_instruction_file = self.qwen_args.get("comment_instruction_file")

    def _get_bio_model(self):
        if self.skip_bio or self.bio_service_url:
            return None
        if self.bio is None:
            from models.BioClip.model import BioClipModel

            self.bio = BioClipModel(**self.bio_clip_args)
        return self.bio

    def _get_bert_model(self):
        if self.skip_bert or self.bert_service_url:
            return None
        if self.bert is None:
            from models.Bert.llm_analyzer import PsychologicalStateAnalyzer

            self.bert = PsychologicalStateAnalyzer(**self.bert_args)
        return self.bert
    
    def _build_image_lookup(folder: Path) -> Dict[str, Path]:
        """Build a filename → path lookup for images.

        First looks in ``class_*`` sub-directories (the original data layout).
        If no ``class_*`` dirs exist, falls back to scanning the folder directly
        for image files (flat layout like Hohhot data).
        """
        lookup: Dict[str, Path] = {}
        class_dirs = list(folder.glob("class_*"))
        if class_dirs:
            for class_dir in class_dirs:
                if not class_dir.is_dir():
                    continue
                for image_path in class_dir.rglob("*"):
                    if image_path.is_file():
                        lookup.setdefault(image_path.name, image_path)
        else:
            # flat layout: images sit directly in the folder
            for image_path in folder.iterdir():
                if image_path.is_file() and image_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"):
                    lookup.setdefault(image_path.name, image_path)
        return lookup

    # ingestion
    def ingest_posts(
        self,
        city_folder: Path,
        max_posts: Optional[int] = None,
        debug: bool = False,
    ) -> int:
        """Ingest posts for all park CSVs inside a city folder.

        Expects `city_folder` to contain CSV files like
        ``1_21_Heiqiao_Park_Chaoyang_District_Beijing.csv`` and corresponding
        park folders with the same stem holding images (either in `class_*`
        subdirs or directly in the folder). Handles CSVs with or without the
        image filename column by using filename heuristics when needed.
        """
        city_path = Path(city_folder)
        if not city_path.is_dir():
            raise FileNotFoundError(f"City folder not found: {city_path}")

        # parse city name like '1Beijing' -> 'Beijing' or '6深圳_...' -> '深圳'
        m = re.match(r"^\d+([^_]+)_", city_path.name)
        if m:
            city_name = m.group(1)
        else:
            m2 = re.match(r"^\d+(.+)", city_path.name)
            city_name = m2.group(1) if m2 else city_path.name

        count = 0
        image_count = 0
        with db.connect(self.dsn) as conn:
            db.ensure_schema(conn)

            for csv_path in sorted(city_path.glob("*.csv")):
                logger.info("ingesting CSV %s", csv_path)
                db.upsert_ingestion_status(conn, filename=str(csv_path), status="processing", last_processed_row=0)

                csv_stem = csv_path.stem
                # park label like 'Heiqiao_Park_Chaoyang_District_Beijing'
                mpark = re.match(r'^(?:\d+_)*(.+)', csv_stem)
                park_label = mpark.group(1) if mpark else csv_stem

                # park folder typically has the same stem as the csv file
                park_dir = city_path / csv_stem
                if not park_dir.is_dir():
                    # fallback to using label-only folder
                    park_dir = city_path / park_label

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
                            return count

                        username = _get(row, "用户名", "原始用户名", "username", "user", "user_name", "name", "昵称")
                        if not username:
                            continue
                        h = hashlib.sha256(username.encode("utf-8")).hexdigest()

                        comment = _get(row, "评论", "text", "comment", "内容") or None
                        # cleanse timestamp: extract an ISO-like date/time or fallback to YYYY-MM-DD
                        raw_time = _get(row, "时间", "timestamp", "time", "date", "日期")
                        timestamp = None
                        if raw_time:
                            m = re.search(r"\d{4}-\d{1,2}-\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?", raw_time)
                            if m:
                                timestamp = m.group(0)
                            else:
                                # try Chinese date like 2020年06月05日 or similar
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
                            # try a few header names when present
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
                            # attach all images whose filename starts with or contains the username
                            if image_lookup:
                                matched = []
                                for name, p in image_lookup.items():
                                    # normalize separators and compare
                                    if name.startswith(username) or name.startswith(username + "_") or name.startswith(username + "-") or username in name:
                                        matched.append(p)
                                for p in matched:
                                    db.insert_image(conn, post_id=post_id, path=str(p), username_hash=h)
                                    image_count += 1

                        db.upsert_ingestion_status(conn, filename=str(csv_path), status="processing", last_processed_row=idx)

                db.upsert_ingestion_status(conn, filename=str(csv_path), status="done", last_processed_row=count)
        logger.info("ingested %d posts and %d images from %s", count, image_count, city_path)

        if debug:
            self.print_sample_posts(limit=5)

        return count

    def print_sample_posts(self, limit: int = 5) -> None:
        """Select `limit` random posts and log the post row plus associated images.

        Tries a direct `post_id` lookup first; if no rows are found, falls back to
        matching images by `username_hash` so samples are informative even when
        images were ingested without `post_id` linkage.
        """
        try:
            with db.connect(self.dsn) as conn2:
                with conn2.cursor() as cur:
                    cur.execute(
                        "SELECT id, city, park, username_hash, comment, time, rating FROM posts ORDER BY RANDOM() LIMIT %s",
                        (limit,),
                    )
                    posts = cur.fetchall()
                    post_ids = [p[0] for p in posts]
                    if not post_ids:
                        logger.info("no posts available to sample")
                        return

                    # fetch all images linked to these post ids in one query (use IN with placeholders)
                    placeholders = ",".join(["%s"] * len(post_ids))
                    cur.execute(
                        f"SELECT id, post_id, username_hash, path FROM images WHERE post_id IN ({placeholders})",
                        tuple(post_ids),
                    )
                    imgs = cur.fetchall()
                    images_by_post: Dict[int, List[dict]] = {}
                    for i in imgs:
                        iid, pid, uh, path = i[0], i[1], i[2], i[3]
                        images_by_post.setdefault(pid, []).append({"id": iid, "username_hash": uh, "path": path})

                    for p in posts:
                        pid = p[0]
                        post_obj = {
                            "id": p[0],
                            "city": p[1],
                            "park": p[2],
                            "username_hash": p[3],
                            "comment": p[4],
                            "time": str(p[5]) if p[5] is not None else None,
                            "rating": p[6],
                        }
                        images = images_by_post.get(pid, [])
                        logger.info("SAMPLE POST: %s", json.dumps(post_obj, ensure_ascii=False))
                        logger.info("ASSOCIATED IMAGES: %s", json.dumps(images, ensure_ascii=False))
        except Exception:
            logger.exception("failed to fetch sample posts/images for inspection")

    # model execution helpers
    def analyze_images(
        self,
        batch_size: int = 1000,
        max_batches: Optional[int] = None,
        workers: int = 1,
    ) -> int:
        """Run BioCLIP on unanalyzed images using the stored file path.

        ``fetch_unanalyzed_images`` returns ``(id, path)`` and the analyzer reads
        each image directly from that path. Results are written to ``image_species``;
        multiple species may be recorded per image. ``workers`` threads share the
        workload; ``max_batches`` limits how many batches each thread processes
        (per-worker).
        """
        total_processed = 0

        def _worker() -> int:
            processed_local = 0
            with db.connect(self.dsn) as conn:
                while True:
                    rows = db.fetch_unanalyzed_images(conn, batch_size)
                    if not rows:
                        break
                    ids: list[int] = []
                    blobs: list[bytes] = []
                    for img_id, img_path in rows:
                        ids.append(img_id)

                        if not img_path:
                            logger.warning("image path missing for id %s", img_id)
                            blobs.append(b"")
                            continue

                        p = Path(img_path)
                        if not p.is_file():
                            logger.warning("image file for id %s path %s not found", img_id, img_path)
                            blobs.append(b"")
                            continue

                        try:
                            with open(p, "rb") as f:
                                blobs.append(f.read())
                        except Exception:
                            logger.exception("failed to read image %s", p)
                            blobs.append(b"")

                    # dispatch to service, local model, or skip
                    if self.bio_service_url:
                        payload = {
                            "images": [base64.b64encode(b).decode("ascii") for b in blobs]
                        }
                        r = requests.post(f"{self.bio_service_url.rstrip('/')}/analyze_images", json=payload)
                        r.raise_for_status()
                        results = r.json().get("results", [])
                    elif self._get_bio_model() is not None:
                        results = self.bio.analyze_image_blobs(blobs, threshold=0.05)
                    else:
                        # no model available, return empty tags
                        results = [([], []) for _ in blobs]

                    for img_id, (species, confidence) in zip(ids, results):
                        db.update_image_analysis(
                            conn, image_id=img_id, species=species, confidence=confidence
                        )
                    processed_local += len(rows)
                    if max_batches is not None and processed_local >= batch_size * max_batches:
                        break
            return processed_local

        if workers <= 1:
            total_processed = _worker()
        else:
            with ThreadPoolExecutor(max_workers=workers) as exe:
                futures = [exe.submit(_worker) for _ in range(workers)]
                for fut in as_completed(futures):
                    total_processed += fut.result()
        return total_processed

    def analyze_posts(self, batch_size: int = 1000, workers: int = 1) -> int:
        """Run sentiment analysis over unscored posts.

        ``workers`` controls the number of threads used; each thread obtains its
        own database connection and continues until no unscored rows remain.
        """
        total = 0

        def _worker() -> int:
            local_count = 0
            with db.connect(self.dsn) as conn:
                while True:
                    rows = db.fetch_posts_for_sentiment(conn, limit=batch_size)
                    if not rows:
                        break
                    post_ids, comments = zip(*rows)

                    if self.bert_service_url:
                        r = requests.post(
                            f"{self.bert_service_url.rstrip('/')}/analyze_posts",
                            json={"comments": list(comments)},
                        )
                        r.raise_for_status()
                        scores = r.json().get("scores", [])
                    else:
                        bert_model = self._get_bert_model()
                        if bert_model is None:
                            raise RuntimeError(
                                "No Bert analyzer available: provide --bert-service-url or remove --skip-bert"
                            )
                        scores = bert_model.batch_analyze(list(comments))

                    for pid, score_dict in zip(post_ids, scores):
                        db.update_bert_sentiment(
                            conn,
                            post_id=pid,
                            score=score_dict["sentiment_score"],
                            label=score_dict.get("sentiment_label", ""),
                        )
                    local_count += len(rows)
            return local_count

        if workers <= 1:
            total = _worker()
        else:
            with ThreadPoolExecutor(max_workers=workers) as exe:
                futures = [exe.submit(_worker) for _ in range(workers)]
                for fut in as_completed(futures):
                    total += fut.result()
        return total

    def run_qwen_image_analysis(self, max_images: Optional[int] = None) -> int:
        """Run Qwen over unanalyzed images individually."""
        instruction = ""
        if self.qwen_image_instruction_file:
            p = Path(self.qwen_image_instruction_file)
            if p.is_file():
                instruction = p.read_text(encoding="utf-8").strip()
                logger.info("loaded qwen image instruction from %s (%d chars)", p, len(instruction))

        config = {
            "instruction": instruction,
            "model": self.qwen_image_model,
        }
        
        # Gather images to process
        with db.connect(self.dsn) as conn:
            # Reusing unanalyzed fetch, or better just fetch all without image_qwen_detail
            limit = max_images if max_images else 1000000
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT i.id, i.path
                    FROM images i
                    LEFT JOIN image_qwen_detail d ON i.id = d.image_id
                    WHERE d.id IS NULL
                    ORDER BY i.id
                    LIMIT %s
                    """,
                    (limit,)
                )
                rows = cur.fetchall()

        if not rows:
            logger.info("no unanalyzed images found for Qwen")
            return 0

        success = 0
        
        # Here we perform inference via the service only.
        if self.qwen_service_url:
            def _normalize_qwen_image_payload(parsed: dict) -> dict:
                if not isinstance(parsed, dict):
                    return {}
                nested = parsed.get("image_analysis_per_image")
                if isinstance(nested, list) and nested:
                    first = nested[0]
                    if isinstance(first, dict):
                        return first
                return parsed

            for img_id, img_path in rows:
                if not img_path:
                    continue
                p = Path(img_path)
                if not p.is_file():
                    continue

                try:
                    with open(p, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("ascii")
                        
                    payload = {
                        "images": [b64],
                        "config": config,
                    }
                    
                    r = requests.post(
                        f"{self.qwen_service_url.rstrip('/')}/analyze_images",
                        json=payload,
                        timeout=300,
                    )
                    r.raise_for_status()
                    results = r.json().get("results", [])
                    if results:
                        parsed_raw = results[0]
                        if isinstance(parsed_raw, dict) and "error" in parsed_raw:
                            logger.warning("qwen image %d returned error: %s", img_id, parsed_raw["error"])
                        else:
                            parsed = _normalize_qwen_image_payload(parsed_raw)
                            vis_species = parsed.get("visible_species_in_image")
                            landscape = parsed.get("landscape_elements")
                            human_acts = parsed.get("human_activities_in_image")
                            plants_detected = parsed.get("plants_detected")
                            animals_detected = parsed.get("animals_detected")
                            human_acts_detected = parsed.get("human_activities_detected")
                            
                            with db.connect(self.dsn) as conn:
                                db.insert_image_qwen_detail(
                                    conn,
                                    image_id=img_id,
                                    image_summary=parsed.get("image_summary"),
                                    visible_species=vis_species if isinstance(vis_species, list) else None,
                                    landscape_elements=landscape if isinstance(landscape, list) else None,
                                    human_activities=human_acts if isinstance(human_acts, list) else None,
                                    plants_detected=plants_detected if isinstance(plants_detected, list) else None,
                                    animals_detected=animals_detected if isinstance(animals_detected, list) else None,
                                    human_activities_detected=human_acts_detected if isinstance(human_acts_detected, list) else None,
                                    raw_response=json.dumps(parsed_raw, ensure_ascii=False)
                                )

                            success += 1
                except Exception as exc:
                    logger.error("qwen image %d failed: %s", img_id, exc)

            logger.info("qwen image service: %d/%d images succeeded", success, len(rows))
            return success
        else:
             logger.warning("No qwen_service_url provided for run_qwen_image_analysis")
             return 0

    def run_qwen_comment_analysis(self, max_posts: Optional[int] = None) -> int:
        """Run Qwen over unanalyzed comments individually."""
        instruction = ""
        if self.qwen_comment_instruction_file:
            p = Path(self.qwen_comment_instruction_file)
            if p.is_file():
                instruction = p.read_text(encoding="utf-8").strip()
                logger.info("loaded qwen comment instruction from %s (%d chars)", p, len(instruction))

        config = {
            "instruction": instruction,
            "model": self.qwen_text_model,
        }
        
        with db.connect(self.dsn) as conn:
            limit = max_posts if max_posts else 1000000
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT p.id, p.comment
                    FROM posts p
                    LEFT JOIN post_qwen_detail d ON p.id = d.post_id
                    WHERE d.id IS NULL AND p.comment IS NOT NULL AND TRIM(p.comment) != ''
                    ORDER BY p.id
                    LIMIT %s
                    """,
                    (limit,)
                )
                rows = cur.fetchall()

        if not rows:
            logger.info("no unanalyzed posts found for Qwen")
            return 0

        success = 0
        if self.qwen_service_url:
            for post_id, comment in rows:
                try:
                    payload = {
                        "comments": [comment],
                        "config": config,
                    }
                    
                    r = requests.post(
                        f"{self.qwen_service_url.rstrip('/')}/analyze_comments",
                        json=payload,
                        timeout=120,
                    )
                    r.raise_for_status()
                    results = r.json().get("results", [])
                    if results:
                        parsed = results[0]
                        if "error" in parsed:
                            logger.warning("qwen post %d returned error: %s", post_id, parsed["error"])
                        else:
                            with db.connect(self.dsn) as conn:
                                emotions = parsed.get("emotions")
                                influence = parsed.get("influence_of_emotions")
                                ts = parsed.get("text_species_mentions")
                                fs = parsed.get("feeling_correlated_to_text_species")
                                ta = parsed.get("text_activities_or_facilities")
                                fa = parsed.get("feeling_correlated_to_text_activities_or_facilities")
                                
                                db.insert_post_qwen_detail(
                                    conn,
                                    post_id=post_id,
                                    emotions=emotions if isinstance(emotions, list) else None,
                                    influence_of_emotions=str(influence) if influence else None,
                                    text_species_mentions=ts if isinstance(ts, list) else None,
                                    feeling_correlated_to_text_species=fs if isinstance(fs, list) else None,
                                    text_activities_or_facilities=ta if isinstance(ta, list) else None,
                                    feeling_correlated_to_text_activities_or_facilities=fa if isinstance(fa, list) else None,
                                    raw_response=json.dumps(parsed, ensure_ascii=False)
                                )
                                
                                sentiment = parsed.get("comment_sentiment", {})
                                sentiment_score = sentiment.get("score_0_to_1") if isinstance(sentiment, dict) else None
                                if sentiment_score is not None:
                                    db.update_qwen_sentiment(conn, post_id=post_id, score=float(sentiment_score))
                                
                            success += 1
                except Exception as exc:
                    logger.error("qwen post %d failed: %s", post_id, exc)

            logger.info("qwen comment service: %d/%d posts succeeded", success, len(rows))
            return len(rows)
        else:
             logger.warning("No qwen_service_url provided for run_qwen_comment_analysis")
             return 0

    def ingest_images(
        self,
        folders: Iterable[Path],
        image_storage: Optional[Path] = None,
    ) -> int:
        """Walk one or more folders (including subdirectories) and ingest images.

        ``username_hash`` is assumed to be the first component of each file's
        stem (split on underscore).  Each image is copied into
        ``image_storage`` using its database id as the filename; the copy path
        is stored in Postgres so analyzers can load the blob directly.
        Progress for each top-level folder is recorded in ``ingestion_status``
        by name.
        
        ``image_storage`` defaults to ``data/images`` relative to the repo root.
        """
        if image_storage is None:
            image_storage = Path("data/images")
        image_storage = image_storage.resolve()
        image_storage.mkdir(parents=True, exist_ok=True)

        inserted = 0
        with db.connect(self.dsn) as conn:
            db.ensure_schema(conn)
            for folder in folders:
                logger.info("scanning images in %s", folder)
                db.upsert_ingestion_status(conn, filename=str(folder), status="processing")
                # walk through all files beneath this folder
                for path in folder.rglob("*"):
                    if not path.is_file():
                        continue
                    # skip hidden/metadata files and CSVs
                    if path.name.startswith('.') or path.suffix.lower() in {'.csv', '.txt'}:
                        continue
                    stem = path.stem
                    username_hash = stem.split("_")[0] if "_" in stem else None
                    try:
                        image_id = db.insert_image(
                            conn,
                            post_id=None,
                            path=str(path),  # passed for compatibility but ignored by PG
                            username_hash=username_hash,
                        )
                    except Exception:
                        logger.exception("failed to insert image %s", path)
                        continue
                    # copy file to storage identified by id and original suffix
                    dest = image_storage / f"{image_id}{path.suffix}"
                    try:
                        shutil.copy2(path, dest)
                    except Exception:
                        logger.exception("failed to copy image %s to %s", path, dest)
                    inserted += 1
                db.upsert_ingestion_status(conn, filename=str(folder), status="done")
        return inserted


# convenience CLI entrypoint

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Manage pipeline ingestion and analysis")
    sub = parser.add_subparsers(dest="command")

    up_csv = sub.add_parser("upload-posts", help="Ingest posts from a city folder containing park CSVs")
    up_csv.add_argument("--city-folder", required=True, help="city folder containing CSV files and park image folders")
    up_csv.add_argument("--image-root", required=False, help="root folder for image paths (optional, unused for city-folder ingestion)")
    up_csv.add_argument("--max-posts", type=int, default=None)
    up_csv.add_argument("--debug", action="store_true", help="log sample posts and images for debugging")

    up_img = sub.add_parser("upload-images", help="Ingest folders of images")
    up_img.add_argument("--folders", nargs="+", required=True, help="folders to scan for images")
    up_img.add_argument("--image-root", required=False, help="directory where images will be copied (default data/images)")

    analyze = sub.add_parser("analyze", help="Run BioCLIP/QL models on ingested data")
    analyze.add_argument("--batch-size", type=int, default=1000)
    analyze.add_argument("--max-batches", type=int, default=None)
    analyze.add_argument("--workers", type=int, default=1)

    qwen_arg = parser.add_argument_group("qwen configuration")
    qwen_arg.add_argument("--qwen-image-model", default="Qwen/Qwen3.5-4B", help="Qwen model name for images")
    qwen_arg.add_argument("--qwen-text-model", default="Qwen/Qwen3.5-4B", help="Qwen model name for comments")
    qwen_arg.add_argument("--qwen-image-instruction-file", default=None)
    qwen_arg.add_argument("--qwen-comment-instruction-file", default=None)

    db_arg = parser.add_argument_group("database")
    db_arg.add_argument("--db-dsn", default=None, help="Postgres DSN or use PIPELINE_DATABASE_DSN env var")

    svc_arg = parser.add_argument_group("services")
    svc_arg.add_argument("--bio-service-url", default=None, help="URL for the BioClip container (e.g. http://localhost:5000)")
    svc_arg.add_argument("--bert-service-url", default=None, help="URL for the Bert container")
    svc_arg.add_argument("--qwen-service-url", default=None, help="URL for the Qwen container")

    skip_arg = parser.add_argument_group("skip models")
    skip_arg.add_argument("--skip-bio", action="store_true", help="do not load or call BioClip locally (use service or skip)")
    skip_arg.add_argument("--skip-bert", action="store_true", help="do not load or call Bert locally")
    skip_arg.add_argument("--skip-qwen", action="store_true", help="do not load or call Qwen locally")

    args = parser.parse_args()

    image_root_arg = getattr(args, "image_root", None)
    dsn = args.db_dsn or os.environ.get("PIPELINE_DATABASE_DSN", "")
    pipeline = Pipeline(
        dsn=dsn,
        bio_clip_args={
            "species_tokens_path": Path("src/models/BioClip/species_tokens_latin.pt"),
            "species_names_path": Path("src/models/BioClip/species_names_latin.txt"),
            "use_half": False,
            "text_batch_size": 4048,
        },
        qwen_args={
            "image_model": args.qwen_image_model,
            "text_model": args.qwen_text_model,
            "image_instruction_file": args.qwen_image_instruction_file,
            "comment_instruction_file": args.qwen_comment_instruction_file,
        },
        bio_service_url=args.bio_service_url,
        bert_service_url=args.bert_service_url,
        qwen_service_url=args.qwen_service_url,
        skip_bio=args.skip_bio,
        skip_bert=args.skip_bert,
        skip_qwen=args.skip_qwen,
    )

    logging.basicConfig(level=logging.INFO)

    if args.command == "upload-posts":
        city_folder = Path(args.city_folder)
        n = pipeline.ingest_posts(city_folder, max_posts=args.max_posts, debug=args.debug)
        logger.info("ingested %d posts from %s", n, city_folder)
        # analyze with Qwen is split now, calling it via `analyze` step ensures separation.
    elif args.command == "upload-images":
        folders = [Path(p) for p in args.folders]
        storage = Path(image_root_arg) if image_root_arg else None
        n = pipeline.ingest_images(folders, image_storage=storage)
        logger.info("ingested %d images", n)
    elif args.command == "analyze":
        nimg = pipeline.analyze_images(batch_size=args.batch_size, max_batches=args.max_batches, workers=args.workers)
        logger.info("processed %d images with BioClip", nimg)
        npost = pipeline.analyze_posts(batch_size=args.batch_size, workers=args.workers)
        logger.info("scored %d posts with Bert", npost)
        
        if not args.skip_qwen:
            nqwen_img = pipeline.run_qwen_image_analysis()
            logger.info("analyzed %d images with Qwen", nqwen_img)
            nqwen_post = pipeline.run_qwen_comment_analysis()
            logger.info("analyzed %d posts with Qwen", nqwen_post)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
