from __future__ import annotations

import sqlite3
from pathlib import Path

import database.postgres as pgmod
import database.sql as sqlmod


def _create_sqlite_species_activity(conn: sqlite3.Connection) -> None:
    # mirror the Postgres schema changes for sqlite tests
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS image_species (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_id INTEGER NOT NULL,
            species TEXT NOT NULL,
            confidence REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS image_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_id INTEGER NOT NULL,
            activity TEXT NOT NULL
        )
        """
    )


def test_species_and_activity_tables(tmp_path: Path):
    # simulate Postgres helpers against a sqlite file
    dbfile = tmp_path / "pg.db"
    real_connect = pgmod.connect
    pgmod.connect = lambda dsn=None: sqlite3.connect(str(dbfile))
    # use the sqlite ensure_schema for posts/images
    pgmod.ensure_schema = sqlmod.ensure_schema

    with pgmod.connect() as conn:
        # create the base tables and our extra ones
        sqlmod.ensure_schema(conn)
        _create_sqlite_species_activity(conn)

        # insert an image row
        img_id = pgmod.insert_image(conn, post_id=None, path="/foo.jpg", username_hash=None)
        # initially it should be returned as unanalyzed
        rows = pgmod.fetch_unanalyzed_images(conn, 10)
        assert rows == [(img_id, None)]

        # add species data
        pgmod.update_image_analysis(conn, image_id=img_id, species=["cat", "dog"], confidence=[0.5, 0.8])
        cur = conn.execute("SELECT species, confidence FROM image_species WHERE image_id=? ORDER BY id", (img_id,))
        assert cur.fetchall() == [("cat", 0.5), ("dog", 0.8)]

        # after insertion, fetch_unanalyzed_images should skip the image
        assert pgmod.fetch_unanalyzed_images(conn, 10) == []

        # adding activity should insert a row
        pgmod.update_image_activity(conn, image_id=img_id, activity="walking")
        act_rows = conn.execute("SELECT activity FROM image_activity WHERE image_id=?", (img_id,)).fetchall()
        assert act_rows == [("walking",)]

    pgmod.connect = real_connect
