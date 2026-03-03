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
from models.Qwen.user_sql_reader import (
    build_qwen_user_batches,
    build_qwen_user_batches_pg,
    build_qwen_messages,
)
from openai import OpenAI


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

    def run_qwen(self, max_users: Optional[int] = None) -> int:
        """Aggregate posts/images into user batches and run Qwen over them.

        Parses the structured JSON response (matching prompt.md schema) and
        persists results into ``qwen_batch_results``, ``image_qwen_detail``,
        ``image_species``, ``image_activity``, and updates ``posts.sentiment_score``.
        """
        instruction = self.qwen_args.get("instruction", "")
        # support reading instruction from a file path
        instruction_file = self.qwen_args.get("instruction_file")
        if instruction_file:
            p = Path(instruction_file)
            if p.is_file():
                instruction = p.read_text(encoding="utf-8").strip()
                logger.info("loaded qwen instruction from %s (%d chars)", p, len(instruction))
            else:
                logger.warning("instruction file %s not found, falling back to inline", p)

        # fetch batches locally (same whether service or local)
        with db.connect(self.dsn) as conn:
            batches = build_qwen_user_batches_pg(
                conn,
                city=self.qwen_args.get("city"),
                park=self.qwen_args.get("park"),
                username=self.qwen_args.get("username"),
                min_images=self.qwen_args.get("min_images", 1),
                max_images=self.qwen_args.get("max_images", 5),
            )
        if max_users is not None:
            batches = batches[:max_users]

        if self.qwen_service_url:
            config = {
                "instruction": instruction,
                "model": self.qwen_args.get("model", "qwen-vl-max"),
                "max_tokens": self.qwen_args.get("max_tokens", 4096),
                "temperature": self.qwen_args.get("temperature", 0.2),
            }
            success = 0
            for i, batch in enumerate(batches, start=1):
                logger.info("qwen service batch %d/%d  city=%s park=%s user=%s  imgs=%d",
                            i, len(batches), batch.city, batch.park, batch.username, len(batch.images))
                payload = {
                    "batches": [batch.to_dict()],
                    "config": config,
                }
                try:
                    r = requests.post(
                        f"{self.qwen_service_url.rstrip('/')}/analyze_users",
                        json=payload,
                        timeout=300,
                    )
                    r.raise_for_status()
                    results = r.json().get("results", [])
                    if results:
                        parsed = results[0]
                        if "error" in parsed:
                            logger.warning("qwen batch %d returned error: %s", i, parsed["error"])
                        else:
                            self._persist_qwen_result(batch, parsed, json.dumps(parsed, ensure_ascii=False))
                            success += 1
                except Exception as exc:
                    logger.error("qwen batch %d failed: %s", i, exc)
            logger.info("qwen service: %d/%d batches succeeded", success, len(batches))
            return len(batches)

        # otherwise use local OpenAI client
        client = OpenAI(api_key=self.qwen_args.get("api_key"), base_url=self.qwen_args.get("base_url"))
        for i, batch in enumerate(batches, start=1):
            messages = build_qwen_messages(batch, instruction)
            resp = client.chat.completions.create(
                model=self.qwen_args.get("model"),
                messages=messages,
                max_tokens=self.qwen_args.get("max_tokens", 4096),
                temperature=self.qwen_args.get("temperature", 0.2),
            )
            raw = resp.choices[0].message.content
            try:
                parsed = json.loads(raw)
                logger.info("qwen batch %d result: %s", i, json.dumps(parsed, ensure_ascii=False))
                self._persist_qwen_result(batch, parsed, raw)
            except Exception:
                logger.warning("qwen returned non-json: %s", raw)
        return len(batches)

    # ── persist helper for new prompt.md JSON schema ────────────────────

    def _persist_qwen_result(self, batch, parsed: dict, raw: str) -> None:
        """Write structured Qwen results into Postgres tables."""
        text_a = parsed.get("text_analysis", {})
        set_level = parsed.get("set_level_extraction", {})
        assoc = parsed.get("image_text_association", {})
        per_image_list = parsed.get("image_analysis_per_image", [])

        # extract text-analysis fields
        emotions = text_a.get("emotions") if isinstance(text_a.get("emotions"), list) else None
        influence = text_a.get("influence_of_emotions")
        tsm = text_a.get("text_species_mentions")
        text_species = tsm if isinstance(tsm, list) else None
        fcts = text_a.get("feeling_correlated_to_text_species")
        feel_species = fcts if isinstance(fcts, list) else None
        taf = text_a.get("text_activities_or_facilities")
        text_activities = taf if isinstance(taf, list) else None
        fctaf = text_a.get("feeling_correlated_to_text_activities_or_facilities")
        feel_activities = fctaf if isinstance(fctaf, list) else None

        sentiment_obj = text_a.get("comment_sentiment", {})
        sentiment_score = sentiment_obj.get("score_0_to_1") if isinstance(sentiment_obj, dict) else None

        assoc_likelihood = assoc.get("association_likelihood_0_to_1")
        assoc_summary = assoc.get("association_summary")

        with db.connect(self.dsn) as conn:
            # 1) Insert batch-level result
            batch_id = db.insert_qwen_batch_result(
                conn,
                city=batch.city,
                park=batch.park,
                username_hash=batch.username,
                post_ids=batch.post_ids,
                raw_response=raw,
                emotions=emotions,
                influence_of_emotions=str(influence) if influence else None,
                text_species_mentions=text_species,
                feeling_correlated_to_text_species=feel_species,
                text_activities_or_facilities=text_activities,
                feeling_correlated_to_text_activities_or_facilities=feel_activities,
                comment_sentiment_score=float(sentiment_score) if sentiment_score is not None else None,
                association_likelihood=float(assoc_likelihood) if assoc_likelihood is not None else None,
                association_summary=assoc_summary,
            )

            # 2) Update qwen_sentiment_score on related posts (independent from Bert)
            if sentiment_score is not None:
                for pid in batch.post_ids:
                    db.update_qwen_sentiment(conn, post_id=pid, score=float(sentiment_score))

            # 3) Per-image detail
            for img_data in per_image_list:
                if not isinstance(img_data, dict):
                    continue
                idx = img_data.get("image_index", 0) - 1  # prompt uses 1-based
                if 0 <= idx < len(batch.images):
                    image_id = batch.images[idx].image_id
                else:
                    continue

                vis_sp = img_data.get("visible_species_in_image")
                vis_species = vis_sp if isinstance(vis_sp, list) else None
                land = img_data.get("landscape_elements")
                landscape = land if isinstance(land, list) else None
                ha = img_data.get("human_activities_in_image")
                acts = ha if isinstance(ha, list) else None

                db.insert_image_qwen_detail(
                    conn,
                    image_id=image_id,
                    batch_result_id=batch_id,
                    image_summary=img_data.get("image_summary"),
                    visible_species=vis_species,
                    landscape_elements=landscape,
                    human_activities=acts,
                )

                # also write per-image activities to image_activity table
                if acts:
                    for act_name in acts:
                        db.update_image_activity(conn, image_id=image_id, activity=str(act_name))

            # 4) Set-level species → image_species (attach to all images in batch)
            plants = set_level.get("plants_detected")
            animals = set_level.get("animals_detected")
            all_species_entries = []
            if isinstance(plants, list):
                all_species_entries.extend(plants)
            if isinstance(animals, list):
                all_species_entries.extend(animals)

            if all_species_entries and batch.images:
                first_image_id = batch.images[0].image_id
                species_names = []
                confidences = []
                for entry in all_species_entries:
                    if isinstance(entry, dict):
                        species_names.append(entry.get("scientific_name", "unknown"))
                        confidences.append(entry.get("confidence", 0.0))
                if species_names:
                    db.update_image_analysis(
                        conn,
                        image_id=first_image_id,
                        species=species_names,
                        confidence=confidences,
                    )

            # 5) Set-level human_activities_detected → image_activity
            set_activities = set_level.get("human_activities_detected")
            if isinstance(set_activities, list) and batch.images:
                first_image_id = batch.images[0].image_id
                for act_entry in set_activities:
                    if isinstance(act_entry, dict):
                        act_name = act_entry.get("activity")
                        if act_name:
                            db.update_image_activity(conn, image_id=first_image_id, activity=str(act_name))

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
    qwen_arg.add_argument("--qwen-instruction", default="", help="System instruction for Qwen VL model (inline text)")
    qwen_arg.add_argument("--qwen-instruction-file", default=None, help="Path to a file containing the Qwen system prompt (overrides --qwen-instruction)")
    qwen_arg.add_argument("--qwen-model", default="qwen-vl-max", help="Qwen model name")
    qwen_arg.add_argument("--qwen-max-tokens", type=int, default=4096, help="Max tokens for Qwen responses")
    qwen_arg.add_argument("--qwen-temperature", type=float, default=0.2, help="Temperature for Qwen inference")
    qwen_arg.add_argument("--qwen-city", default=None, help="Filter for specific city")
    qwen_arg.add_argument("--qwen-park", default=None, help="Filter for specific park")
    qwen_arg.add_argument("--qwen-username", default=None, help="Filter for specific username")
    qwen_arg.add_argument("--qwen-min-images", type=int, default=1, help="Minimum images per user batch")
    qwen_arg.add_argument("--qwen-max-images", type=int, default=5, help="Max images per user batch (0=unlimited)")

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
            "instruction": args.qwen_instruction,
            "instruction_file": args.qwen_instruction_file,
            "model": args.qwen_model,
            "max_tokens": args.qwen_max_tokens,
            "temperature": args.qwen_temperature,
            "city": args.qwen_city,
            "park": args.qwen_park,
            "username": args.qwen_username,
            "min_images": args.qwen_min_images,
            "max_images": args.qwen_max_images,
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
        # analyze with Qwen
        if not args.skip_qwen:
            nusers = pipeline.run_qwen()
            logger.info("analyzed %d user batches with Qwen", nusers)
    elif args.command == "upload-images":
        folders = [Path(p) for p in args.folders]
        storage = Path(image_root_arg) if image_root_arg else None
        n = pipeline.ingest_images(folders, image_storage=storage)
        logger.info("ingested %d images", n)
    elif args.command == "analyze":
        nimg = pipeline.analyze_images(batch_size=args.batch_size, max_batches=args.max_batches, workers=args.workers)
        logger.info("processed %d images", nimg)
        npost = pipeline.analyze_posts(batch_size=args.batch_size, workers=args.workers)
        logger.info("scored %d posts", npost)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
