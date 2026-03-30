"""Utility to load JSON pipeline results and persist into Postgres.

Usage:
    python -m pipeline.json_to_postgres --db-dsn "dbname=..." results1.json results2.json

This script expects JSON files produced by the orchestrator's `--output-json` mode.
It will insert rows into the same schema the orchestrator uses: `posts`, `images`,
`image_species` / `image_analysis` equivalents, `post_qwen_detail`, `image_qwen_detail`,
and sentiment updates.

This utility tries to be idempotent where possible by skipping existing image
paths and posts by (city,park,username_hash,comment,time) fingerprint.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, Any

from database import postgres as db

logger = logging.getLogger(__name__)


def _post_fingerprint(p: Dict[str, Any]) -> str:
    """Create a simple fingerprint for a post to detect duplicates."""
    # Compose fields that identify a post uniquely for this loader
    city = p.get("city") or ""
    park = p.get("park") or ""
    uh = p.get("username_hash") or p.get("username_hash") or ""
    comment = (p.get("comment") or "")[:512]
    time = p.get("time") or ""
    return "||".join([city, park, uh, time, comment])


def load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def insert_results(dsn: str, data: Dict[str, Any]) -> None:
    """Insert data from a single JSON object into Postgres via `database.postgres` helpers.

    The function assumes the DB schema already exists.
    """
    with db.connect(dsn) as conn:
        db.ensure_schema(conn)

        # keep a small mapping of JSON post id -> DB post id
        json_post_to_db: Dict[int, int] = {}

        # Insert posts if not present
        posts = data.get("posts", []) or []
        for p in posts:
            # fingerprint lookup to avoid duplicate inserts
            fp = _post_fingerprint(p)
            existing = db.find_post_by_fingerprint(conn, fp)
            if existing:
                db_post_id = existing[0]
                logger.debug("post exists, using id %s", db_post_id)
            else:
                db_post_id = db.insert_post(
                    conn,
                    city=p.get("city"),
                    park=p.get("park"),
                    username=p.get("username") or "",
                    username_hash=p.get("username_hash") or None,
                    comment=p.get("comment"),
                    time=p.get("time"),
                    rating=p.get("rating"),
                )
            json_post_to_db[p.get("id")] = db_post_id

        # Insert images; avoid re-inserting identical paths
        images = data.get("images", []) or []
        for img in images:
            path = img.get("path")
            post_id = img.get("post_id")
            db_post = json_post_to_db.get(post_id)
            if db.image_path_exists(conn, path):
                logger.debug("image path already exists: %s", path)
                continue
            # insert image linked to post if we have a mapping
            try:
                db.insert_image(conn, post_id=db_post, path=path, username_hash=img.get("username_hash"))
            except Exception:
                logger.exception("failed to insert image %s", path)

        # Insert image analysis results if present
        for ia in data.get("image_analysis", []) or []:
            img_id = ia.get("image_id")
            species = ia.get("species")
            confidence = ia.get("confidence")
            try:
                # image_id in JSON refers to in-file ids; attempt to find by path if available
                # Here we rely on image entries to have been inserted; otherwise skip.
                db.update_image_analysis(conn, image_id=img_id, species=species, confidence=confidence)
            except Exception:
                logger.debug("could not update image_analysis for image_id %s", img_id)

        # Insert post sentiment if present
        for s in data.get("post_sentiment", []) or []:
            pid = s.get("post_id")
            db_pid = json_post_to_db.get(pid)
            if db_pid is None:
                logger.debug("skip sentiment for unknown post id %s", pid)
                continue
            try:
                db.update_bert_sentiment(conn, post_id=db_pid, score=s.get("score"), label=s.get("label") or "")
            except Exception:
                logger.exception("failed to update sentiment for post %s", db_pid)

        # Insert Qwen details for images
        for iq in data.get("image_qwen_detail", []) or []:
            img_id = iq.get("image_id")
            # try to map to DB image id via path if available
            # (JSON may not include path here; we skip if not resolvable)
            try:
                db.insert_image_qwen_detail(
                    conn,
                    image_id=img_id,
                    image_summary=iq.get("image_summary"),
                    visible_species=iq.get("visible_species"),
                    landscape_elements=iq.get("landscape_elements"),
                    human_activities=iq.get("human_activities"),
                    plants_detected=iq.get("plants_detected"),
                    animals_detected=iq.get("animals_detected"),
                    human_activities_detected=iq.get("human_activities_detected"),
                    raw_response=iq.get("raw_response"),
                )
            except Exception:
                logger.exception("failed to insert image_qwen_detail for image %s", img_id)

        # Insert Qwen post details
        for pq in data.get("post_qwen_detail", []) or []:
            post_id = pq.get("post_id")
            db_pid = json_post_to_db.get(post_id)
            if db_pid is None:
                logger.debug("skip post_qwen_detail for unknown post id %s", post_id)
                continue
            try:
                db.insert_post_qwen_detail(
                    conn,
                    post_id=db_pid,
                    emotions=pq.get("emotions"),
                    influence_of_emotions=pq.get("influence_of_emotions"),
                    text_species_mentions=pq.get("text_species_mentions"),
                    feeling_correlated_to_text_species=pq.get("feeling_correlated_to_text_species"),
                    text_activities_or_facilities=pq.get("text_activities_or_facilities"),
                    feeling_correlated_to_text_activities_or_facilities=pq.get("feeling_correlated_to_text_activities_or_facilities"),
                    raw_response=pq.get("raw_response"),
                )
            except Exception:
                logger.exception("failed to insert post_qwen_detail for post %s", db_pid)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load pipeline JSON results into Postgres")
    parser.add_argument("--db-dsn", required=True, help="Postgres DSN")
    parser.add_argument("files", nargs="+", help="JSON result files to load")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    dsn = args.db_dsn
    for f in args.files:
        p = Path(f)
        if not p.is_file():
            logger.warning("skipping missing file %s", f)
            continue
        data = load_json(p)
        insert_results(dsn, data)


if __name__ == "__main__":
    main()
