import argparse
import json
import logging
import hashlib
import re
import sys
from pathlib import Path
from typing import Optional

# Ensure src is in path for imports
src_dir = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from database import postgres as db
from database import sql as sqlmod

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("import_standalone_qwen")

def get_park_label(csv_filename: str) -> str:
    csv_stem = csv_filename.replace('.csv', '')
    mpark = re.match(r'^(?:\d+_)*(.+)', csv_stem)
    return mpark.group(1) if mpark else csv_stem

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

def process_comments(conn, comments_file: Path):
    if not comments_file.exists():
        logger.warning(f"Comments file not found: {comments_file}")
        return

    logger.info(f"Processing comments from {comments_file}")
    success_count = 0
    fail_count = 0
    
    with open(comments_file, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            try:
                record = json.loads(line)
                if not record.get("parse_ok"):
                    continue
                
                post_id = get_post_id(conn, record["username"], record["csv_filename"], record["directory"])
                if not post_id:
                    fail_count += 1
                    continue
                
                parsed = record.get("parsed_json", {})
                emotions = parsed.get("emotions")
                influence = parsed.get("influence_of_emotions")
                if isinstance(emotions, list):
                    emotions = ",".join(str(e) for e in emotions)
                
                text_species = parsed.get("text_species_mentions")
                if isinstance(text_species, list): text_species = ",".join(str(e) for e in text_species)
                
                text_activities = parsed.get("text_activities_or_facilities")
                if isinstance(text_activities, list): text_activities = ",".join(str(e) for e in text_activities)
                
                feeling_species = parsed.get("feeling_correlated_to_text_species")
                feeling_activities = parsed.get("feeling_correlated_to_text_activities_or_facilities")

                # Delete existing to prevent duplicate constraint issues if re-running
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM post_qwen_detail WHERE post_id = %s", (post_id,))
                
                db.insert_post_qwen_detail(
                    conn,
                    post_id=post_id,
                    emotions=emotions,
                    influence_of_emotions=influence,
                    text_species_mentions=text_species,
                    feeling_correlated_to_text_species=feeling_species,
                    text_activities_or_facilities=text_activities,
                    feeling_correlated_to_text_activities_or_facilities=feeling_activities,
                    raw_response=record.get("raw_response")
                )
                success_count += 1
            except Exception as e:
                logger.error(f"Error processing record: {e}")
                fail_count += 1
                
    logger.info(f"Comments: Inserted/Updated {success_count} records. Failed to match {fail_count} records.")

def process_images(conn, images_file: Path):
    if not images_file.exists():
        logger.warning(f"Images file not found: {images_file}")
        return

    logger.info(f"Processing images from {images_file}")
    success_count = 0
    fail_count = 0
    
    with open(images_file, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            try:
                record = json.loads(line)
                if not record.get("parse_ok"):
                    continue
                
                image_id = get_image_id(conn, record["image_filename"])
                if not image_id:
                    fail_count += 1
                    continue
                
                parsed = record.get("parsed_json", {})
                
                def list_to_str(val):
                    if isinstance(val, list): return ",".join(str(e) for e in val)
                    return str(val) if val else None

                # Delete existing
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM image_qwen_detail WHERE image_id = %s", (image_id,))
                
                db.insert_image_qwen_detail(
                    conn,
                    image_id=image_id,
                    image_summary=parsed.get("image_summary"),
                    visible_species=list_to_str(parsed.get("visible_species")),
                    landscape_elements=list_to_str(parsed.get("landscape_elements")),
                    human_activities=parsed.get("human_activities"),
                    plants_detected=list_to_str(parsed.get("plants_detected")),
                    animals_detected=list_to_str(parsed.get("animals_detected")),
                    human_activities_detected=list_to_str(parsed.get("human_activities_detected")),
                    raw_response=record.get("raw_response")
                )
                success_count += 1
            except Exception as e:
                logger.error(f"Error processing image record: {e}")
                fail_count += 1

    logger.info(f"Images: Inserted/Updated {success_count} records. Failed to match {fail_count} records.")

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
        logger.info(f"Connected successfully.")
        
        process_comments(conn, comments_file)
        process_images(conn, images_file)
        
if __name__ == "__main__":
    main()
