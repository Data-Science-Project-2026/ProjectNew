import tempfile
import sqlite3
import shutil
import os
from pathlib import Path
import sys

# Ensure the local `src` package root is importable when running this script
root = Path(__file__).resolve().parents[1]
root_str = str(root)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

# Setup a temporary workspace with CSV and image
td_raw = tempfile.mkdtemp()
td = Path(td_raw)

csv_dir = td / "csvs"
csv_dir.mkdir()
city_dir = csv_dir / "1TestCity"
city_dir.mkdir()
csv_path = city_dir / "1_ParkA.csv"
csv_path.write_text("park,username,rating,text,timestamp,image\nParkA,user1,5,hello world,2020-01-01,image1.jpg\n", encoding="utf-8")
park_img_dir = city_dir / "1_ParkA"
park_img_dir.mkdir()
(park_img_dir / "image1.jpg").write_bytes(b"\xff\xd8\xff")

# create a db file
dbfile = td / "test.db"

# monkeypatch postgres helpers to use sqlite for this run
import database.postgres as pgmod
import database.sql as sqlmod

def fake_connect(dsn=None):
    return sqlite3.connect(str(dbfile))

pgmod.connect = fake_connect
pgmod.ensure_schema = sqlmod.ensure_schema
pgmod.insert_post = sqlmod.insert_post
pgmod.insert_image = sqlmod.insert_image
pgmod.upsert_ingestion_status = sqlmod.upsert_ingestion_status
# sqlite-compatible helpers for post fetching/updating
pgmod.fetch_posts_for_sentiment = sqlmod.fetch_posts_for_sentiment
pgmod.update_bert_sentiment = sqlmod.update_bert_sentiment

def _sqlite_get_status(conn, filename):
    row = conn.execute(
        "SELECT id, filename, status, last_processed_row, created_at, updated_at FROM ingestion_status WHERE filename = ?",
        (filename,),
    ).fetchone()
    return None if row is None else (row[0], row[1], row[2], row[3], row[4], row[5])

def _sqlite_image_path_exists(conn, path):
    row = conn.execute("SELECT 1 FROM images WHERE path = ? LIMIT 1", (path,)).fetchone()
    return row is not None

pgmod.get_ingestion_status = _sqlite_get_status
pgmod.image_path_exists = _sqlite_image_path_exists

# patch BioClipModel to avoid loading heavy models
import models.BioClip.model as bcmod
real_init = bcmod.BioClipModel.__init__
def _fake_init(self, *args, **kwargs):
    self.species_tokens = []
    self.species_names = []
    self.model = None
    self.device = "cpu"
bcmod.BioClipModel.__init__ = _fake_init

real_analyze = bcmod.BioClipModel.analyze_image_blobs
def _fake_analyze(self, blobs, threshold=0.05):
    # emulate: return empty species/confidence for each blob
    return [([], []) for _ in blobs]
bcmod.BioClipModel.analyze_image_blobs = _fake_analyze

# run pipeline
from pipeline.orchestrator import Pipeline
p = Pipeline(
    dsn=str(dbfile),
    bio_clip_args={
        "species_tokens_path": Path("/dev/null"),
        "species_names_path": Path("/dev/null"),
        "use_half": False,
        "text_batch_size": 1,
    },
    bert_args={},
    skip_bert=False,
    skip_qwen=True,
)

# provide a lightweight dummy bert model to avoid heavy downloads
class DummyBert:
    def batch_analyze(self, comments):
        return [{"sentiment_score": 0.5, "sentiment_label": "neutral"} for _ in comments]

p.bert = DummyBert()
p.skip_bert = False

print("Running ingest_posts...")
nposts = p.ingest_posts(city_dir)
print("ingested posts:", nposts)

print("Running ingest_images...")
nimgs = p.ingest_images([td])
print("ingested images:", nimgs)

print("Running analyze_images...")
na = p.analyze_images(batch_size=10, max_batches=1)
print("analyze_images processed:", na)

print("Running analyze_posts...")
np = p.analyze_posts(batch_size=10)
print("analyze_posts processed:", np)

# restore patches
bcmod.BioClipModel.__init__ = real_init
bcmod.BioClipModel.analyze_image_blobs = real_analyze

print("Test run complete. DB file at:", dbfile)

print("Temporary directory retained at:", td)
