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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, List, Optional, Dict

from database import postgres as db


logger = logging.getLogger(__name__)
from pipeline.ingestion import ingest_posts_impl, ingest_images_impl
from pipeline.analysis import analyze_images_impl, analyze_posts_impl
from pipeline.qwen import run_qwen_image_analysis_impl, run_qwen_comment_analysis_impl


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
        output_json: Optional[str] = None,
        bio_service_url: Optional[str] = None,
        bert_service_url: Optional[str] = None,
        qwen_service_url: Optional[str] = None,
        skip_bio: bool = False,
        skip_bert: bool = False,
        skip_qwen: bool = False,
    ) -> None:
        self.dsn = dsn
        self.output_json = output_json
        # if output_json is provided we operate in no-db mode and gather results
        # in an in-memory store which will be written to disk at the end.
        if self.output_json:
            self._json_store: Dict[str, list] = {
                "posts": [],
                "images": [],
                "image_analysis": [],
                "post_sentiment": [],
                "image_qwen_detail": [],
                "post_qwen_detail": [],
                "ingestion_status": [],
            }
            self._next_post_id = 1
            self._next_image_id = 1

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

    def print_sample_posts(self, limit: int = 5) -> None:
        """Select `limit` random posts and log the post row plus associated images.

        Tries a direct `post_id` lookup first; if no rows are found, falls back to
        matching images by `username_hash` so samples are informative even when
        images were ingested without `post_id` linkage.
        """
        try:
            if self.output_json:
                posts = list(self._json_store.get("posts", []))
                if not posts:
                    logger.info("no posts available to sample")
                    return
                import random

                sample = random.sample(posts, min(limit, len(posts)))
                images = list(self._json_store.get("images", []))
                images_by_post: Dict[int, List[dict]] = {}
                for i in images:
                    images_by_post.setdefault(i.get("post_id"), []).append({"id": i.get("id"), "username_hash": i.get("username_hash"), "path": i.get("path")})
                for p in sample:
                    pid = p.get("id")
                    post_obj = p.copy()
                    logger.info("SAMPLE POST: %s", json.dumps(post_obj, ensure_ascii=False))
                    logger.info("ASSOCIATED IMAGES: %s", json.dumps(images_by_post.get(pid, []), ensure_ascii=False))
            else:
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

    def load_images_from_folder(self, folder: Path) -> int:
        """Scan *folder* recursively for image files and add them to the JSON store.

        Only meaningful in JSON/no-db mode (``output_json`` is set).  Each
        discovered image file is appended to ``_json_store["images"]`` with
        ``post_id=None`` so that subsequent analysis steps (e.g. Qwen) can
        process them without requiring a prior ingestion run.

        Returns the number of images added.
        """
        if not self.output_json:
            logger.warning("load_images_from_folder called outside JSON mode; no-op")
            return 0

        image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}
        added = 0
        existing_paths = {img["path"] for img in self._json_store.get("images", [])}
        for p in sorted(folder.rglob("*")):
            if p.is_file() and p.suffix.lower() in image_exts:
                path_str = str(p)
                if path_str in existing_paths:
                    continue
                image_id = self._next_image_id
                self._next_image_id += 1
                self._json_store["images"].append({
                    "id": image_id,
                    "post_id": None,
                    "path": path_str,
                    "username_hash": None,
                })
                existing_paths.add(path_str)
                added += 1
        logger.info("load_images_from_folder: added %d images from %s", added, folder)
        return added

    # ingestion delegators
    def ingest_posts(
        self,
        csv_folder: Path,
        images_root: Optional[Path] = None,
        max_posts: Optional[int] = None,
        debug: bool = False,
    ) -> int:
        """Delegate post ingestion to the ingestion helper."""
        return ingest_posts_impl(self, csv_folder, images_root=images_root, max_posts=max_posts, debug=debug)

    def ingest_images(
        self,
        folders: Iterable[Path],
        image_storage: Optional[Path] = None,
    ) -> int:
        """Delegate image ingestion to the ingestion helper."""
        return ingest_images_impl(self, folders, image_storage=image_storage)

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
        return analyze_images_impl(self, batch_size=batch_size, max_batches=max_batches, workers=workers)

    def analyze_posts(self, batch_size: int = 1000, workers: int = 1) -> int:
        """Run sentiment analysis over unscored posts.

        ``workers`` controls the number of threads used; each thread obtains its
        own database connection and continues until no unscored rows remain.
        """
        return analyze_posts_impl(self, batch_size=batch_size, workers=workers)

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
        
        use_json = bool(self.output_json)

        # Gather images to process
        if use_json:
            limit = max_images if max_images else 1000000
            all_images = list(self._json_store.get("images", []))
            existing = {d.get("image_id") for d in self._json_store.get("image_qwen_detail", [])}
            rows = [(img["id"], img.get("path")) for img in all_images if img["id"] not in existing][:limit]
        else:
            with db.connect(self.dsn) as conn:
                # Reusing unanalyzed fetch, or better just fetch all without image_qwen_detail
                limit = max_images if max_images else 1000000
                try:
                    import sqlite3  # type: ignore
                except Exception:
                    sqlite3 = None  # type: ignore

                if sqlite3 is not None and isinstance(conn, sqlite3.Connection):
                    cur = conn.cursor()
                    try:
                        # if image_qwen_detail doesn't exist (sqlite tests), select all images
                        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='image_qwen_detail'")
                        if cur.fetchone() is None:
                            cur.execute(
                                "SELECT id, path FROM images ORDER BY id LIMIT ?",
                                (limit,),
                            )
                        else:
                            cur.execute(
                                """
                                SELECT i.id, i.path
                                FROM images i
                                LEFT JOIN image_qwen_detail d ON i.id = d.image_id
                                WHERE d.id IS NULL
                                ORDER BY i.id
                                LIMIT ?
                                """,
                                (limit,)
                            )
                        rows = cur.fetchall()
                    finally:
                        try:
                            cur.close()
                        except Exception:
                            pass
                else:
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
                            
                            if use_json:
                                self._json_store.setdefault("image_qwen_detail", []).append({
                                    "image_id": img_id,
                                    "image_summary": parsed.get("image_summary"),
                                    "visible_species": vis_species if isinstance(vis_species, list) else None,
                                    "landscape_elements": landscape if isinstance(landscape, list) else None,
                                    "human_activities": human_acts if isinstance(human_acts, list) else None,
                                    "plants_detected": plants_detected if isinstance(plants_detected, list) else None,
                                    "animals_detected": animals_detected if isinstance(animals_detected, list) else None,
                                    "human_activities_detected": human_acts_detected if isinstance(human_acts_detected, list) else None,
                                    "raw_response": json.dumps(parsed_raw, ensure_ascii=False),
                                })
                            else:
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
        return run_qwen_comment_analysis_impl(self, max_posts=max_posts)

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
        return ingest_images_impl(self, folders, image_storage=image_storage)

    def dump_results(self, path: Optional[str] = None) -> None:
        """Write the in-memory JSON results to `path` (or the configured output_json)."""
        p = path or self.output_json
        if not p:
            raise ValueError("no output path provided for JSON dump")
        try:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(self._json_store, fh, ensure_ascii=False, indent=2)
            logger.info("wrote JSON results to %s", p)
        except Exception:
            logger.exception("failed to write JSON results to %s", p)


# convenience CLI entrypoint

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Manage pipeline ingestion and analysis")
    sub = parser.add_subparsers(dest="command")

    up_csv = sub.add_parser("upload-posts", help="Ingest posts from a folder containing CSV files")
    up_csv.add_argument("--csv-folder", required=True, help="folder containing CSV files")
    up_csv.add_argument("--image-folder", required=False, help="root folder where park image folders live")
    up_csv.add_argument("--max-posts", type=int, default=None)
    up_csv.add_argument("--debug", action="store_true", help="log sample posts and images for debugging")

    up_img = sub.add_parser("upload-images", help="Ingest folders of images")
    up_img.add_argument("--folders", nargs="+", required=True, help="folders to scan for images")
    up_img.add_argument("--image-root", required=False, help="directory where images will be copied (default data/images)")

    analyze = sub.add_parser("analyze", help="Run BioCLIP/QL models on ingested data")
    analyze.add_argument("--batch-size", type=int, default=1000)
    analyze.add_argument("--max-batches", type=int, default=None)
    analyze.add_argument("--workers", type=int, default=1)
    analyze.add_argument("--images-root", required=False, help="folder of images to load into JSON store before analysis (JSON mode only)")

    qwen_arg = parser.add_argument_group("qwen configuration")
    qwen_arg.add_argument("--qwen-image-model", default="Qwen/Qwen3.5-4B", help="Qwen model name for images")
    qwen_arg.add_argument("--qwen-text-model", default="Qwen/Qwen3.5-4B", help="Qwen model name for comments")
    qwen_arg.add_argument("--qwen-image-instruction-file", default=None)
    qwen_arg.add_argument("--qwen-comment-instruction-file", default=None)

    db_arg = parser.add_argument_group("database")
    db_arg.add_argument("--db-dsn", default=None, help="Postgres DSN or use PIPELINE_DATABASE_DSN env var")
    db_arg.add_argument("--output-json", default=None, help="path to write JSON results; disables DB usage")

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
        output_json=args.output_json,
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
        csv_folder = Path(args.csv_folder)
        images_root = Path(args.image_folder) if getattr(args, "image_folder", None) else None
        t0 = time.perf_counter()
        n = pipeline.ingest_posts(csv_folder, images_root=images_root, max_posts=args.max_posts, debug=args.debug)
        dt = time.perf_counter() - t0
        logger.info("ingested %d posts from %s", n, csv_folder)
        logger.info("ingest_posts duration: %.3f seconds", dt)
        # analyze with Qwen is split now, calling it via `analyze` step ensures separation.
    elif args.command == "upload-images":
        folders = [Path(p) for p in args.folders]
        storage = Path(image_root_arg) if image_root_arg else None
        t0 = time.perf_counter()
        n = pipeline.ingest_images(folders, image_storage=storage)
        dt = time.perf_counter() - t0
        logger.info("ingested %d images", n)
        logger.info("ingest_images duration: %.3f seconds", dt)
    elif args.command == "analyze":
        images_root = getattr(args, "images_root", None)
        if pipeline.output_json and images_root:
            pipeline.load_images_from_folder(Path(images_root))
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

    # If running in JSON/no-db mode, dump the collected results
    if getattr(args, "output_json", None):
        try:
            pipeline.dump_results(args.output_json)
        except Exception:
            logger.exception("failed to dump JSON results")


if __name__ == "__main__":
    main()
