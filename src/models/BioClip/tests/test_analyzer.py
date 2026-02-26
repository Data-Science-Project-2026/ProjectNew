from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from models.BioClip.analyzer import BioClipAnalyzer


def test_bioclip_analyzer_no_rows(tmp_path: Path) -> None:
    # monkeypatch Postgres helpers to use a temporary sqlite DB
    import database.postgres as pgmod
    import database.sql as sqlmod

    real_connect = pgmod.connect
    pgmod.connect = lambda dsn=None: sqlite3.connect(str(tmp_path / "db.db"))
    pgmod.ensure_schema = sqlmod.ensure_schema
    # ensure tables exist
    with pgmod.connect() as conn:
        sqlmod.ensure_schema(conn)

    # dummy model that records inputs
    seen: list = []

    class DummyModel:
        def analyze_image_blobs(self, blobs, threshold=0.05):
            seen.append((blobs, threshold))
            return [([], []) for _ in blobs]

    analyzer = BioClipAnalyzer(
        dsn="unused",
        model=DummyModel(),
        batch_size=10,
        threshold=0.1,
        image_root=tmp_path / "imgs",
    )

    # there are no images in the database yet
    processed = analyzer.analyze_images()
    assert processed == 0
    assert seen == []

    # cleanup
    pgmod.connect = real_connect
