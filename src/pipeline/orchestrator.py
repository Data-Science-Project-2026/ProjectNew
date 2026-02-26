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
from models.BioClip.model import BioClipModel

from models.Bert.llm_analyzer import PsychologicalStateAnalyzer
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

        # local model instantiation
        if not self.bio_service_url and not self.skip_bio:
            self.bio = BioClipModel(**bio_clip_args)
        else:
            self.bio = None
        if not self.bert_service_url and not self.skip_bert:
            self.bert = PsychologicalStateAnalyzer(**(bert_args or {}))
        else:
            self.bert = None
        self.qwen_args = qwen_args or {}

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
                # mark file pending/processing
                db.upsert_ingestion_status(conn, filename=str(path), status="processing", last_processed_row=0)
                with open(path, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for idx, row in enumerate(reader, start=1):
                        if max_posts and count >= max_posts:
                            db.upsert_ingestion_status(conn, filename=str(path), status="done", last_processed_row=count)
                            return count

                        # compute username hash
                        username = row.get("username", "") or ""
                        h = hashlib.sha256(username.encode("utf-8")).hexdigest()

                        # some CSVs only contain a single "park" column; if a
                        # separate "city" field exists we will read it, otherwise we
                        # duplicate the value so that both columns are non-null.
                        post_id = db.insert_post(
                            conn,
                            city=row.get("city", row.get("park", "")) or "",
                            park=row.get("park", "") or "",
                            username=username,
                            username_hash=h,
                            comment=row.get("text") or None,
                            time=row.get("timestamp") or None,
                            rating=row.get("rating") or None,
                        )
                        count += 1
                        # update progress row
                        db.upsert_ingestion_status(conn, filename=str(path), status="processing", last_processed_row=idx)

                        image_path = row.get("image")
                        if image_path and image_root is not None:
                            full = image_root / image_path
                            if full.exists():
                                # derive username_hash from filename if encoded
                                img_hash = None
                                try:
                                    img_hash = Path(image_path).stem.split("_")[0]
                                except Exception:
                                    img_hash = None
                                db.insert_image(conn, post_id=post_id, path=str(image_path), username_hash=img_hash)
                            else:
                                logger.warning("image %s not found", full)
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
                    elif self.bio:
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
                        scores = self.bert.batch_analyze(list(comments))

                    for pid, score_dict in zip(post_ids, scores):
                        db.update_post_sentiment(
                            conn, post_id=pid, sentiment_score=score_dict["sentiment_score"]
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

        Results are **logged**; callers may wish to parse and persist them.
        """
        # fetch batches locally (same whether service or local)
        with db.connect(self.dsn) as conn:
            batches = build_qwen_user_batches_pg(
                conn,
                city=self.qwen_args.get("city"),
                park=self.qwen_args.get("park"),
                username=self.qwen_args.get("username"),
                min_images=self.qwen_args.get("min_images", 1),
            )
        if max_users is not None:
            batches = batches[:max_users]

        if self.qwen_service_url:
            # serialize minimal batch info
            payload = {"batches": [batch.to_dict() for batch in batches]}
            r = requests.post(f"{self.qwen_service_url.rstrip('/')}/analyze_users", json=payload)
            r.raise_for_status()
            results = r.json().get("results", [])
            # results assumed list matching batches with activities
            if results:
                for batch, parsed in zip(batches, results):
                    if "human_activities" in parsed:
                        with db.connect(self.dsn) as conn:
                            for activity_entry in parsed.get("human_activities", []):
                                act = activity_entry.get("activity")
                                for idx in activity_entry.get("evidence_images", []):
                                    if 0 <= idx < len(batch.images):
                                        image_id = batch.images[idx].image_id
                                        db.update_image_activity(conn, image_id=image_id, activity=act)
            return len(batches)

        # otherwise use local OpenAI client
        client = OpenAI(api_key=self.qwen_args.get("api_key"), base_url=self.qwen_args.get("base_url"))
        for i, batch in enumerate(batches, start=1):
            messages = build_qwen_messages(batch, self.qwen_args.get("instruction"))
            resp = client.chat.completions.create(
                model=self.qwen_args.get("model"),
                messages=messages,
                max_tokens=self.qwen_args.get("max_tokens", 512),
                temperature=self.qwen_args.get("temperature", 0.2),
            )
            try:
                parsed = json.loads(resp.choices[0].message.content)
                logger.info("qwen batch %d result: %s", i, json.dumps(parsed, ensure_ascii=False))

                # write activity information back to Postgres so downstream
                # queries can filter/images by detected activities.
                if "human_activities" in parsed:
                    with db.connect(self.dsn) as conn:
                        for activity_entry in parsed.get("human_activities", []):
                            act = activity_entry.get("activity")
                            for idx in activity_entry.get("evidence_images", []):
                                if 0 <= idx < len(batch.images):
                                    image_id = batch.images[idx].image_id
                                    db.update_image_activity(conn, image_id=image_id, activity=act)
            except Exception:
                logger.warning("qwen returned non-json: %s", resp.choices[0].message.content)
        return len(batches)

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

    pipeline = Pipeline(
        dsn=args.db_dsn or os.environ.get("PIPELINE_DATABASE_DSN"),
        bio_clip_args={
            "species_tokens_path": Path("src/models/BioClip/species_tokens_latin.pt"),
            "species_names_path": Path("src/models/BioClip/species_names_latin.txt"),
            "use_half": False,
            "text_batch_size": 4048,
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
