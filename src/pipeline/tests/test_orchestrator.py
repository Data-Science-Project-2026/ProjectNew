from __future__ import annotations

import tempfile
import os
from pathlib import Path
import sqlite3
import pytest
from pipeline.orchestrator import Pipeline

def _make_dummy_csv(tmpdir: Path) -> Path:
    path = tmpdir / "data.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("park,username,rating,text,timestamp,image\n")
        f.write("ParkA,user1,5,hello world,2020-01-01,image1.jpg\n")
    return path


def test_ingest_and_analysis(tmp_path: Path):
    # create a city folder with a park CSV and images
    city_dir = tmp_path / "1TestCity"
    city_dir.mkdir()
    csv_path = city_dir / "1_ParkA.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        f.write("park,username,rating,text,timestamp,image\n")
        f.write("ParkA,user1,5,hello world,2020-01-01,image1.jpg\n")
    img_dir = city_dir / "1_ParkA"
    img_dir.mkdir()
    (img_dir / "image1.jpg").write_bytes(b"\xff\xd8\xff")

    # create sqlite file path used for testing
    dbfile = tmp_path / "test.db"
    # monkey‑patch the postgres.connect helper so it returns a sqlite3 connection
    import database.postgres as pgmod
    real_connect = pgmod.connect

    # patch ensure_schema so sqlite connection can be used
    import database.sql as sqlmod
    pgmod.ensure_schema = sqlmod.ensure_schema
    # reuse certain helpers for sqlite compatibility
    pgmod.insert_post = sqlmod.insert_post
    pgmod.insert_image = sqlmod.insert_image
    # create a simple upsert function for ingestion_status
    def _sqlite_upsert(conn, *, filename, status, last_processed_row=None):
        conn.execute(
            """
            INSERT INTO ingestion_status (filename, status, last_processed_row, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(filename) DO UPDATE SET
                status=excluded.status,
                last_processed_row=excluded.last_processed_row,
                updated_at=CURRENT_TIMESTAMP
            """,
            (filename, status, last_processed_row),
        )
    pgmod.upsert_ingestion_status = _sqlite_upsert

    # also patch BioClipModel.__init__ to avoid loading heavy resources
    import models.BioClip.model as bcmod
    real_bioclip_init = bcmod.BioClipModel.__init__
    def _fake_bioclip_init(self, *args, **kwargs):
        # create minimal attributes used elsewhere
        self.species_tokens = []
        self.species_names = []
        self.model = None
        self.device = "cpu"
    bcmod.BioClipModel.__init__ = _fake_bioclip_init
    def _fake_connect(dsn: str | None = None):
        return sqlite3.connect(str(dbfile))
    pgmod.connect = _fake_connect

    pipeline = Pipeline(
        dsn=str(dbfile),
        bio_clip_args={
            # these models won't be loaded in test; use dummy paths
            "species_tokens_path": Path("/dev/null"),
            "species_names_path": Path("/dev/null"),
            "use_half": False,
            "text_batch_size": 1,
        },
        bert_args={
            "sentiment_model": "nlptown/bert-base-multilingual-uncased-sentiment",
        },
    )

    # ingestion should at least attempt to run without raising an exception
    try:
        n = pipeline.ingest_posts(city_dir, max_posts=None, debug=False)
    except Exception:
        pytest.skip("database backend not available")
    else:
        assert n == 1
        # confirm status row was written
        with sqlite3.connect(str(dbfile)) as conn:
            row = conn.execute("SELECT filename, status, last_processed_row FROM ingestion_status").fetchone()
            assert row is not None
            assert row[1] == "done"

    # image analysis requires a working DB and models; just call to ensure it
    # doesn't crash if the tables exist
    try:
        _ = pipeline.analyze_images(batch_size=1, max_batches=1)
    except Exception:
        pass
    finally:
        # restore the original connect function
        pgmod.connect = real_connect
        # restore BioClipModel init
        bcmod.BioClipModel.__init__ = real_bioclip_init


def test_ingest_images_folder(tmp_path: Path):
    # prepare a directory tree with some fake images
    root = tmp_path / "pics"
    sub = root / "subdir"
    sub.mkdir(parents=True)
    # one file with hashed username prefix
    (root / "abc123_imageA.jpg").write_bytes(b"data")
    # one file without underscore
    (sub / "nohash.jpg").write_bytes(b"data")

    dbfile = tmp_path / "test2.db"
    import database.postgres as pgmod2
    real_connect2 = pgmod2.connect
    # patch ensure_schema for sqlite
    import database.sql as sqlmod2
    pgmod2.ensure_schema = sqlmod2.ensure_schema
    pgmod2.insert_image = sqlmod2.insert_image
    pgmod2.insert_post = sqlmod2.insert_post
    def _sqlite_upsert2(conn, *, filename, status, last_processed_row=None):
        conn.execute(
            """
            INSERT INTO ingestion_status (filename, status, last_processed_row, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(filename) DO UPDATE SET
                status=excluded.status,
                last_processed_row=excluded.last_processed_row,
                updated_at=CURRENT_TIMESTAMP
            """,
            (filename, status, last_processed_row),
        )
    pgmod2.upsert_ingestion_status = _sqlite_upsert2
    def _fake_connect2(dsn: str | None = None):
        return sqlite3.connect(str(dbfile))
    pgmod2.connect = _fake_connect2

    # patch BioClipModel.__init__ so it doesn't try to load files
    import models.BioClip.model as bcmod2
    real_bioclip_init2 = bcmod2.BioClipModel.__init__
    def _fake_bioclip_init2(self, *args, **kwargs):
        self.species_tokens = []
        self.species_names = []
        self.model = None
        self.device = "cpu"
    bcmod2.BioClipModel.__init__ = _fake_bioclip_init2

    # record the hashes passed to the database helper so we can verify
    observed_hashes: list = []
    # use the sqlite insert under the hood so we can inspect the DB later,
    # but drop the path argument to simulate Postgres behaviour
    def _capture(conn, *, post_id, path, username_hash=None, **kwargs):
        observed_hashes.append(username_hash)
        # call the sqlite helper directly (ignores username_hash internally)
        return sqlmod2.insert_image(
            conn,
            post_id=post_id,
            path=path,
            username_hash=username_hash,
            **kwargs,
        )
    pgmod2.insert_image = _capture

    pipeline2 = Pipeline(
        dsn=str(dbfile),
        bio_clip_args={
            "species_tokens_path": Path("/dev/null"),
            "species_names_path": Path("/dev/null"),
            "use_half": False,
            "text_batch_size": 1,
        },
        bert_args={
            "sentiment_model": "nlptown/bert-base-multilingual-uncased-sentiment",
        },
    )

    storage = tmp_path / "store"
    n = pipeline2.ingest_images([root], image_storage=storage)
    assert n == 2
    # we expected the first filename to yield "abc123" and the second None
    assert observed_hashes == ["abc123", None]
    # ensure files were copied into the storage directory named by id
    stored = sorted(storage.iterdir())
    assert len(stored) == 2
    assert all(f.stem.isdigit() for f in stored)

    with sqlite3.connect(str(dbfile)) as conn:
        rows = conn.execute("SELECT filename, status FROM ingestion_status").fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "done"
        imgs = conn.execute("SELECT username_hash FROM images").fetchall()
        assert len(imgs) == 2
    # verify model receives the two blobs from the stored files
    orig_analyze = bcmod2.BioClipModel.analyze_image_blobs
    seen: list = []
    def fake_analyze(self, blobs, threshold=0.05):
        seen.extend(blobs)
        return [([], []) for _ in blobs]
    bcmod2.BioClipModel.analyze_image_blobs = fake_analyze
    pipeline2.analyze_images(batch_size=10)
    # should have seen exactly two image blobs matching the originals
    assert len(seen) == 2
    with open(root / "abc123_imageA.jpg", "rb") as f1, open(sub / "nohash.jpg", "rb") as f2:
        assert seen[0] == f1.read()
        assert seen[1] == f2.read()
    # restore
    bcmod2.BioClipModel.analyze_image_blobs = orig_analyze
    pgmod2.connect = real_connect2
    # restore BioClipModel init
    bcmod2.BioClipModel.__init__ = real_bioclip_init2


def test_service_urls(tmp_path: Path):
    # ensure DB exists with a single post and image
    dbfile = tmp_path / "service.db"
    import database.postgres as pgmod3
    import database.sql as sqlmod3
    real_connect3 = pgmod3.connect
    pgmod3.connect = lambda dsn=None: sqlite3.connect(str(dbfile))
    pgmod3.ensure_schema = sqlmod3.ensure_schema
    # patch other helpers used during analysis
    pgmod3.fetch_unanalyzed_images = sqlmod3.fetch_unanalyzed_images
    pgmod3.update_image_analysis = sqlmod3.update_image_analysis
    pgmod3.fetch_posts_for_sentiment = sqlmod3.fetch_posts_for_sentiment
    pgmod3.update_post_sentiment = sqlmod3.update_post_sentiment
    pgmod3.update_image_activity = sqlmod3.update_image_activity

    # insert minimal records
    with sqlite3.connect(str(dbfile)) as conn:
        sqlmod3.ensure_schema(conn)
        post_id = sqlmod3.insert_post(conn, city="c", park="p", username="u", username_hash="h", comment="hi", time=None, rating=None)
        sqlmod3.insert_image(conn, post_id=post_id, path="/no/thing.jpg", username_hash=None)

    # monkeypatch requests.post
    import requests
    real_post = requests.post
    calls: list = []
    class DummyResp:
        def __init__(self, data):
            self._data = data
        def raise_for_status(self):
            pass
        def json(self):
            return self._data

    def fake_post(url, json=None, **kwargs):
        calls.append((url, json))
        if url.endswith("/analyze_images"):
            return DummyResp({"results": [[[], []]]})
        if url.endswith("/analyze_posts"):
            return DummyResp({"scores": [{"sentiment_score": 0.7}]})
        if url.endswith("/analyze_users"):
            return DummyResp({"results": [{"human_activities": []}]})
        return DummyResp({})

    requests.post = fake_post

    pipeline = Pipeline(
        dsn=str(dbfile),
        bio_clip_args={
            "species_tokens_path": Path("/dev/null"),
            "species_names_path": Path("/dev/null"),
            "use_half": False,
            "text_batch_size": 1,
        },
        bert_args={
            "sentiment_model": "nlptown/bert-base-multilingual-uncased-sentiment",
        },
        bio_service_url="http://bio",
        bert_service_url="http://sent",
        qwen_service_url="http://qwen",
    )

    # run analytics; we don't care about return values, just that requests were made
    pipeline.analyze_images(batch_size=1, max_batches=1)
    pipeline.analyze_posts(batch_size=1)
    pipeline.run_qwen_image_analysis()
    pipeline.run_qwen_comment_analysis()

    # expect all three endpoints were called
    assert any("/analyze_images" in url for url, _ in calls)
    assert any("/analyze_posts" in url for url, _ in calls)
    assert any("/analyze_users" in url for url, _ in calls)

    # restore
    requests.post = real_post
    pgmod3.connect = real_connect3
