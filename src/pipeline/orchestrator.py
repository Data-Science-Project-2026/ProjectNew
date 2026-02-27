from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import base64
import shutil
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, List, Optional

from database import postgres as db
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

    # ingestion
    def ingest_posts(
        self,
        csv_paths: Iterable[Path],
        image_root: Optional[Path] = None,
        max_posts: Optional[int] = None,
    ) -> int:
        """Read CSV files and add records to Postgres, tracking progress.

        The CSV filename is recorded in ``ingestion_status`` so a later run can
        resume from ``last_processed_row``.  ``max_posts`` may be used for
        testing; if provided we stop after that many rows across all files.
        """
        """Read CSV files and add records (and optionally images) to Postgres.

        ``csv_paths`` may be a list of concrete files or a glob pattern.
        ``image_root`` is the directory where relative image paths should be
        resolved.  If a row does not reference an image or the file cannot be
        read, ``image`` is left ``NULL`` and ingestion continues.

        Returns the number of posts ingested.
        """
        count = 0
        with db.connect(self.dsn) as conn:
            db.ensure_schema(conn)

            for path in csv_paths:
                logger.info("ingesting %s", path)
                db.upsert_ingestion_status(conn, filename=str(path), status="processing", last_processed_row=0)

                # derive city / park from CSV filename
                # e.g. "3_1_Panshan_Scenic_Area_Jizhou_District_Tianjin.csv"
                csv_stem = Path(path).stem  # "3_1_Panshan_..._Tianjin"
                # take last part after splitting by _ as city guess
                csv_city = csv_stem.rsplit("_", 1)[-1] if "_" in csv_stem else csv_stem
                csv_park = csv_stem

                with open(path, newline="", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for idx, row in enumerate(reader, start=1):
                        if max_posts and count >= max_posts:
                            db.upsert_ingestion_status(conn, filename=str(path), status="done", last_processed_row=count)
                            return count

                        # read Chinese column names (from csv_to_sql convention)
                        username = (row.get("用户名") or row.get("username") or "").strip()
                        h = hashlib.sha256(username.encode("utf-8")).hexdigest()

                        comment = (row.get("评论") or row.get("text") or "").strip() or None
                        timestamp = (row.get("时间") or row.get("timestamp") or "").strip() or None
                        rating = (row.get("评分") or row.get("rating") or "").strip() or None

                        post_id = db.insert_post(
                            conn,
                            city=row.get("city", csv_city) or csv_city,
                            park=row.get("park", csv_park) or csv_park,
                            username=username,
                            username_hash=h,
                            comment=comment,
                            time=timestamp,
                            rating=rating,
                        )
                        count += 1
                        db.upsert_ingestion_status(conn, filename=str(path), status="processing", last_processed_row=idx)

                        # handle multi-image: semicolon-separated filenames
                        raw_images = row.get("图像文件名列表") or row.get("image") or ""
                        filenames = [s.strip() for s in raw_images.replace("|", ";").replace(",", ";").split(";") if s.strip()]

                        for img_name in filenames:
                            if image_root is not None:
                                full = image_root / img_name
                                if not full.exists():
                                    logger.debug("image %s not found", full)
                                    continue
                            db.insert_image(
                                conn,
                                post_id=post_id,
                                path=img_name,
                                username_hash=h,
                            )

                db.upsert_ingestion_status(conn, filename=str(path), status="done", last_processed_row=count)
        return count

    # model execution helpers
    def analyze_images(
        self,
        batch_size: int = 1000,
        max_batches: Optional[int] = None,
        workers: int = 1,
        image_root: Optional[Path] = None,
    ) -> int:
        """Run BioCLIP on unanalyzed images using files stored on disk.

        The Postgres database no longer retains file paths; instead the
        ingestor copies each image to ``image_root`` (default ``data/images``)
        using the numeric image id as the filename.  ``fetch_unanalyzed_images``
        returns ``(id, username_hash)`` tuples.  ``image_root`` **must** be
        provided when using Postgres so that the worker can locate each file.

        Results are written to the normalized ``image_species`` table rather
        than the ``images`` row itself.  Multiple species entries may be
        recorded per image.  Activities are handled similarly elsewhere.

        ``workers`` threads share the workload; ``max_batches`` limits how many
        batches each thread processes (per-worker).
        """
        if image_root is None:
            image_root = Path("data/images")
        total_processed = 0

        def _worker() -> int:
            processed_local = 0
            with db.connect(self.dsn) as conn:
                while True:
                    rows = db.fetch_unanalyzed_images(conn, batch_size)
                    if not rows:
                        break
                    ids, hashes = zip(*rows)
                    blobs: list[bytes] = []
                    for img_id in ids:
                        # locate file by id in the image_root directory
                        found = list(Path(image_root).glob(f"{img_id}.*"))
                        if not found:
                            logger.warning("image file for id %s not found", img_id)
                            blobs.append(b"")
                            continue
                        fp = found[0]
                        try:
                            with open(fp, "rb") as f:
                                blobs.append(f.read())
                        except Exception:
                            logger.exception("failed to read image %s", fp)
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
                image_root=self.qwen_args.get("image_root"),
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
        ``image_storage`` using its database id as the filename; **no path is
        stored** in PostgreSQL, fulfilling our privacy requirement.  Progress
        for each top-level folder is recorded in ``ingestion_status`` by name.
        
        ``image_storage`` defaults to ``data/images`` relative to the repo root.
        """
        if image_storage is None:
            image_storage = Path("data/images")
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

    up_csv = sub.add_parser("upload-posts", help="Ingest one or more CSV files containing posts")
    up_csv.add_argument("--csv-dir", required=True, help="directory containing CSV files")
    up_csv.add_argument("--image-root", required=False, help="root folder for image paths (optional)")
    up_csv.add_argument("--max-posts", type=int, default=None)

    up_img = sub.add_parser("upload-images", help="Ingest folders of images")
    up_img.add_argument("--folders", nargs="+", required=True, help="folders to scan for images")
    up_img.add_argument("--image-root", required=False, help="directory where images will be copied (default data/images)")

    analyze = sub.add_parser("analyze", help="Run BioCLIP/QL models on ingested data")
    analyze.add_argument("--batch-size", type=int, default=1000)
    analyze.add_argument("--max-batches", type=int, default=None)
    analyze.add_argument("--workers", type=int, default=1)
    analyze.add_argument("--image-root", required=False, help="root for image files when analyzing")

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
            "image_root": args.image_root,
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
        files = Path(args.csv_dir).glob("*.csv")
        n = pipeline.ingest_posts(files, image_root=Path(args.image_root) if args.image_root else None, max_posts=args.max_posts)
        logger.info("ingested %d posts", n)
        # analyze with Qwen
        if not args.skip_qwen:
            nusers = pipeline.run_qwen()
            logger.info("analyzed %d user batches with Qwen", nusers)
    elif args.command == "upload-images":
        folders = [Path(p) for p in args.folders]
        storage = Path(args.image_root) if args.image_root else None
        n = pipeline.ingest_images(folders, image_storage=storage)
        logger.info("ingested %d images", n)
    elif args.command == "analyze":
        nimg = pipeline.analyze_images(batch_size=args.batch_size, max_batches=args.max_batches, workers=args.workers, image_root=Path(args.image_root) if args.image_root else None)
        logger.info("processed %d images", nimg)
        npost = pipeline.analyze_posts(batch_size=args.batch_size, workers=args.workers)
        logger.info("scored %d posts", npost)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
