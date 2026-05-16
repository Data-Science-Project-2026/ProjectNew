import argparse
import json
import logging
import hashlib
import re
import sys
from pathlib import Path
from typing import Optional

POST_CACHE = {}
IMAGE_CACHE = {}

# Ensure src is in path for imports
src_dir = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from database import postgres as db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("import_standalone_qwen")

def get_park_label(csv_filename: str) -> str:
    csv_stem = csv_filename.replace('.csv', '')
    mpark = re.match(r'^(?:\d+_)*(.+)', csv_stem)
    return mpark.group(1) if mpark else csv_stem

def get_post_id(conn, username: str, csv_filename: str, city_dir: str, comment_text: Optional[str] = None):

    username = str(username).strip()
    h = hashlib.sha256(username.encode("utf-8")).hexdigest()
    park_label = get_park_label(csv_filename)

    # CACHE KEYS:
    key1 = (h, park_label, comment_text)
    key2 = (h, park_label)
    key3 = ("__hash_only__", h)

    # CACHE CHECK
    if key1 in POST_CACHE:
        return POST_CACHE[key1]
    if key2 in POST_CACHE:
        return POST_CACHE[key2]
    if key3 in POST_CACHE:
        return POST_CACHE[key3]

    with conn.cursor() as cur:
         # 1. exact match (best)
        if comment_text:
            cur.execute(
                """
                SELECT id
                FROM posts
                WHERE username_hash=%s AND park=%s AND comment=%s
                LIMIT 1
                """,
                (h, park_label, comment_text),
            )
            row = cur.fetchone()
            if row:
                POST_CACHE[key1] = row[0]
                POST_CACHE[key2] = row[0]
                POST_CACHE[key3] = row[0]
                return row[0]

        # 2. hash + park
        cur.execute(
            """
            SELECT id
            FROM posts
            WHERE username_hash=%s AND park=%s
            LIMIT 1
            """,
            (h, park_label),
        )
        row = cur.fetchone()
        if row:
            POST_CACHE[key2] = row[0]
            POST_CACHE[key3] = row[0]
            return row[0]

        # 3. fallback: hash only
        cur.execute(
            """
            SELECT id
            FROM posts
            WHERE username_hash=%s
            LIMIT 2
            """,
            (h,),
        )
        rows = cur.fetchall()
        if len(rows) == 1:
            POST_CACHE[key3] = rows[0][0]
            return rows[0][0]

    return None

def get_image_id(conn, image_filename: str) -> Optional[int]:

    image_filename = image_filename.strip()

    if image_filename in IMAGE_CACHE:
        return IMAGE_CACHE[image_filename]

    with conn.cursor() as cur:

        cur.execute(
            "SELECT id FROM images WHERE path LIKE %s LIMIT 1",
            (f"%/{image_filename}",),
        )
        row = cur.fetchone()
        if row:
            IMAGE_CACHE[image_filename] = row[0]
            return row[0]

        cur.execute(
            "SELECT id FROM images WHERE path LIKE %s LIMIT 1",
            (f"%{image_filename}",),
        )
        row = cur.fetchone()
        if row:
            IMAGE_CACHE[image_filename] = row[0]
            return row[0]

    return None

def process_comments(conn, comments_file: Path):

    logger.info(f"Processing comments from {comments_file}")

    success = fail = skip = 0

    with open(comments_file, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):

            if i % 10000 == 0:
                logger.info(
                    f"[COMMENTS] {i} rows | success={success} fail={fail} skip={skip}"
                )

            if not line.strip():
                continue

            try:
                record = json.loads(line)

                if not record.get("parse_ok"):
                    skip += 1
                    continue

                post_id = get_post_id(
                    conn,
                    record["username"],
                    record["csv_filename"],
                    record["directory"],
                    comment_text=record.get("comment_text"),
                )

                if not post_id:
                    fail += 1
                    continue

                parsed = record.get("parsed_json", {})
                if "text_analysis" in parsed:
                    parsed = parsed["text_analysis"]

                def join_if_list(x):
                    return ",".join(map(str, x)) if isinstance(x, list) else x

                emotions = join_if_list(parsed.get("emotions"))
                influence = parsed.get("influence_of_emotions")
                species = join_if_list(parsed.get("text_species_mentions"))
                activities = join_if_list(parsed.get("text_activities_or_facilities"))
                feeling_species = join_if_list(parsed.get("feeling_correlated_to_text_species"))
                feeling_activities = join_if_list(parsed.get("feeling_correlated_to_text_activities_or_facilities"))

                sentiment_obj = parsed.get("comment_sentiment", {})
                sentiment_score = None

                if isinstance(sentiment_obj, dict):
                    sentiment_score = sentiment_obj.get("score_0_to_1")
                elif isinstance(sentiment_obj, (int, float)):
                    sentiment_score = float(sentiment_obj)

                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM post_qwen_detail WHERE post_id=%s",
                        (post_id,),
                    )

                db.insert_post_qwen_detail(
                    conn,
                    post_id=post_id,
                    emotions=emotions,
                    influence_of_emotions=influence,
                    text_species_mentions=species,
                    feeling_correlated_to_text_species=feeling_species,
                    text_activities_or_facilities=activities,
                    feeling_correlated_to_text_activities_or_facilities=feeling_activities,
                    raw_response=record.get("raw_response"),
                )

                if sentiment_score is not None:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE posts
                            SET qwen_sentiment_score=%s, qwen_status='ready'
                            WHERE id=%s
                            """,
                            (sentiment_score, post_id),
                        )
                    conn.commit()

                success += 1

            except Exception as e:
                logger.error(f"Error line {i}: {e}")
                fail += 1

    logger.info(f"[COMMENTS DONE] success={success} fail={fail} skip={skip}")

def process_images(conn, images_file: Path):

    logger.info(f"Processing images from {images_file}")

    success = fail = skip = 0

    with open(images_file, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):

            if i % 10000 == 0:
                logger.info(f"[IMAGES] {i} rows | success={success} fail={fail} skip={skip}")

            if not line.strip():
                continue

            try:
                record = json.loads(line)

                if not record.get("parse_ok"):
                    skip += 1
                    continue

                image_id = get_image_id(conn, record["image_filename"])
                if not image_id:
                    fail += 1
                    continue

                parsed = record.get("parsed_json", {})
                if "image_analysis" in parsed:
                    parsed = parsed["image_analysis"]

                def to_str(x):
                    return ",".join(map(str, x)) if isinstance(x, list) else x

                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM image_qwen_detail WHERE image_id=%s",
                        (image_id,),
                    )

                db.insert_image_qwen_detail(
                    conn,
                    image_id=image_id,
                    image_summary=parsed.get("image_summary"),
                    visible_species=to_str(parsed.get("visible_species")),
                    landscape_elements=to_str(parsed.get("landscape_elements")),
                    human_activities=parsed.get("human_activities"),
                    plants_detected=to_str(parsed.get("plants_detected")),
                    animals_detected=to_str(parsed.get("animals_detected")),
                    human_activities_detected=to_str(parsed.get("human_activities_detected")),
                    raw_response=record.get("raw_response"),
                )

                success += 1

            except Exception as e:
                logger.error(f"Image error line {i}: {e}")
                fail += 1

    logger.info(f"[IMAGES DONE] success={success} fail={fail} skip={skip}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--db-dsn", required=True)
    args = parser.parse_args()

    results_dir = Path(args.results_dir)

    comments_file = results_dir / "comments_output.jsonl"
    images_file = results_dir / "images_output.jsonl"

    logger.info("Connecting DB...")

    with db.connect(args.db_dsn) as conn:
        db.ensure_schema(conn)
        logger.info("Schema OK")

        process_comments(conn, comments_file)
        process_images(conn, images_file)


if __name__ == "__main__":
    main()
