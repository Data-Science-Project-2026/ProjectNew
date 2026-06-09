import argparse
import json
import logging
import hashlib
import re
import sys
from pathlib import Path
from typing import Optional
import time

# Ensure src is in path for imports
src_dir = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from database import postgres as db
from database import sql as sqlmod

BATCH_SIZE = 3000
SUCCESS = 0
FAIL = 0
TOTAL = 0

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("import_standalone_qwen")

def get_park_label(csv_filename: str) -> str:
    csv_stem = csv_filename.replace('.csv', '')
    mpark = re.match(r'^(?:\d+_)*(.+)', csv_stem)
    return mpark.group(1) if mpark else csv_stem

def preload_posts(conn):
    cur = conn.cursor()
    cur.execute("SELECT id, username_hash, park, comment FROM posts")

    m = {}
    for pid, h, park, comment in cur.fetchall():
        m[(h, park, comment)] = pid
        m[(h, park)] = pid
        m[(h,)] = pid

    return m

def preload_images(conn):
    cur = conn.cursor()
    cur.execute("SELECT id, path FROM images")

    m = {}
    for iid, path in cur.fetchall():
        m[path.split("/")[-1]] = iid

    return m

def log_progress(name, i, ok, fail, start):
    elapsed = time.time() - start
    rate = i / elapsed if elapsed else 0

    print(
        f"[{name}] processed={i:,} | ok={ok:,} | fail={fail:,} | {rate:.1f} rows/s"
    )

def flush_comments(conn, batch):
    cur = conn.cursor()

    cur.executemany("""
        INSERT INTO post_qwen_detail (
            post_id,
            emotions,
            influence_of_emotions,
            text_species_mentions,
            text_activities_or_facilities,
            feeling_correlated_to_text_species,
            feeling_correlated_to_text_activities_or_facilities,
            raw_response
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (post_id)
        DO UPDATE SET
            emotions = EXCLUDED.emotions,
            influence_of_emotions = EXCLUDED.influence_of_emotions,
            text_species_mentions = EXCLUDED.text_species_mentions,
            text_activities_or_facilities = EXCLUDED.text_activities_or_facilities,
            feeling_correlated_to_text_species = EXCLUDED.feeling_correlated_to_text_species,
            feeling_correlated_to_text_activities_or_facilities = EXCLUDED.feeling_correlated_to_text_activities_or_facilities,
            raw_response = EXCLUDED.raw_response
    """, batch)

    conn.commit()

def flush_images(conn, batch):
    cur = conn.cursor()

    for row in batch:
        cur.execute("""
            INSERT INTO image_qwen_detail (
                image_id,
                image_summary,
                visible_species,
                landscape_elements,
                human_activities,
                plants_detected,
                animals_detected,
                human_activities_detected,
                raw_response
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (image_id)
            DO UPDATE SET
                image_summary = EXCLUDED.image_summary,
                visible_species = EXCLUDED.visible_species,
                landscape_elements = EXCLUDED.landscape_elements,
                human_activities = EXCLUDED.human_activities,
                plants_detected = EXCLUDED.plants_detected,
                animals_detected = EXCLUDED.animals_detected,
                human_activities_detected = EXCLUDED.human_activities_detected,
                raw_response = EXCLUDED.raw_response
        """, row)

    conn.commit()

def get_post_id(conn, username: str, csv_filename: str, city_dir: str) -> Optional[int]:
    h = hashlib.sha256(username.encode("utf-8")).hexdigest()
    park_label = get_park_label(csv_filename)
    
    with conn.cursor() as cur:
        # First try exact match with park and username_hash
        cur.execute("SELECT id FROM posts WHERE username_hash = %s AND park = %s LIMIT 1", (h, park_label))
        row = cur.fetchone()
        if row:
            return row[0]
        
        # If not, try just username_hash if it's unique
        cur.execute("SELECT id FROM posts WHERE username_hash = %s LIMIT 2", (h,))
        rows = cur.fetchall()
        if len(rows) == 1:
            return rows[0][0]

    return None

def get_image_id(conn, image_filename: str) -> Optional[int]:
    # We look for the image path ending with the filename
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM images WHERE path LIKE %s LIMIT 1", (f"%/{image_filename}",))
        row = cur.fetchone()
        if row:
            return row[0]
        
        # try exact filename if stored securely
        cur.execute("SELECT id FROM images WHERE path LIKE %s LIMIT 1", (f"%{image_filename}",))
        row = cur.fetchone()
        if row:
            return row[0]
            
    return None

def process_comments(conn, file, post_map):
    start = time.time()
    global SUCCESS, FAIL, TOTAL
    SUCCESS = FAIL = TOTAL = 0

    logger.info(f"Processing comments from {file}")

    batch = []

    with open(file, "r", encoding="utf-8") as f:
        for line in f:
            TOTAL += 1

            if not line.strip():
                continue

            try:
                record = json.loads(line)
                if not record.get("parse_ok"):
                    continue

                h = hashlib.sha256(record["username"].strip().encode()).hexdigest()
                park = get_park_label(record["csv_filename"])
                comment = record.get("comment_text")

                post_id = (
                    post_map.get((h, park, comment))
                    or post_map.get((h, park))
                    or post_map.get((h,))
                )

                if not post_id:
                    FAIL += 1
                    continue

                parsed = record.get("parsed_json", {}).get("text_analysis", {})

                emotions = parsed.get("emotions")
                if isinstance(emotions, list):
                    emotions = ",".join(map(str, emotions))

                batch.append((
                    post_id,
                    emotions,
                    parsed.get("influence_of_emotions"),
                    parsed.get("text_species_mentions"),
                    parsed.get("text_activities_or_facilities"),
                    parsed.get("feeling_correlated_to_text_species"),
                    parsed.get("feeling_correlated_to_text_activities_or_facilities"),
                    record.get("raw_response"),
                ))
                SUCCESS += 1

                if len(batch) >= BATCH_SIZE:
                    flush_comments(conn, batch)
                    batch.clear()

                if TOTAL % 1000 == 0:
                    log_progress("COMMENTS", TOTAL, SUCCESS, FAIL, start)

            except Exception as e:
                logger.error(e)

    log_final("COMMENTS", TOTAL, SUCCESS, FAIL, start)
    
    if batch:
        flush_comments(conn, batch)

def process_images(conn, file, image_map):
    start = time.time()
    global SUCCESS, FAIL, TOTAL
    SUCCESS = FAIL = TOTAL = 0

    logger.info(f"Processing images from {file}")

    batch = []

    with open(file, "r", encoding="utf-8") as f:
        for line in f:
            TOTAL += 1

            if not line.strip():
                continue

            try:
                record = json.loads(line)
                if not record.get("parse_ok"):
                    continue

                image_id = image_map.get(record["image_filename"].strip())
                if not image_id:
                    FAIL += 1
                    continue

                parsed = record.get("parsed_json", {}).get("image_analysis", {})

                def s(x):
                    return ",".join(map(str, x)) if isinstance(x, list) else x

                batch.append((
                    image_id,
                    parsed.get("image_summary"),
                    s(parsed.get("visible_species")),
                    s(parsed.get("landscape_elements")),
                    parsed.get("human_activities"),
                    s(parsed.get("plants_detected")),
                    s(parsed.get("animals_detected")),
                    s(parsed.get("human_activities_detected")),
                    record.get("raw_response"),
                ))
                SUCCESS += 1

                if len(batch) >= BATCH_SIZE:
                    flush_images(conn, batch)
                    batch.clear()

                if TOTAL % 1000 == 0:
                    log_progress("IMAGES", TOTAL, SUCCESS, FAIL, start)

            except Exception as e:
                logger.error(e)

    log_final("IMAGES", TOTAL, SUCCESS, FAIL, start)

    if batch:
        flush_images(conn, batch)

def log_final(name, total, ok, fail, start):
    elapsed = time.time() - start
    rate = total / elapsed if elapsed else 0

    print(
        f"\n[{name} DONE] "
        f"processed={total:,} | ok={ok:,} | fail={fail:,} | "
        f"{rate:.1f} rows/s\n"
    )

def main():
    parser = argparse.ArgumentParser(description="Import standalone Qwen inference JSONL results into PostgreSQL.")
    parser.add_argument("--results-dir", type=str, required=True, help="Path to the directory containing JSONL output files (e.g. results/1Beijing)")
    parser.add_argument("--db-dsn", type=str, required=True, help="PostgreSQL DSN string (e.g. postgresql://user:pass@localhost:5432/mydb)")
    
    args = parser.parse_args()
    
    results_dir = Path(args.results_dir)
    if not results_dir.exists() or not results_dir.is_dir():
        logger.error(f"Results directory does not exist or is not a directory: {results_dir}")
        sys.exit(1)
        
    comments_file = results_dir / "comments_output.jsonl"
    images_file = results_dir / "images_output.jsonl"

    logger.info(f"Connecting to database...")
    with db.connect(args.db_dsn) as conn:
        db.ensure_schema(conn)

        logger.info("Preloading caches...")
        post_map = preload_posts(conn)
        image_map = preload_images(conn)

        process_comments(conn, comments_file, post_map)
        process_images(conn, images_file, image_map)
        
if __name__ == "__main__":
    main()
