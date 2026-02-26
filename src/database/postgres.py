from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Sequence

import psycopg2


# NOTE: this module mirrors the sqlite/sql.py API but targets a
# PostgreSQL connection.  It is intentionally lightweight so that the
# orchestrator can switch DB backends without duplicating business
# logic elsewhere.


def connect(dsn: str | None = None) -> psycopg2.extensions.connection:
    """Return a new psycopg2 connection using DSN or environment variable.

    ``dsn`` may be any string accepted by :func:`psycopg2.connect` (e.g.
    ``"dbname=... user=... password=... host=..."``) or, when omitted, the
    value of ``PIPELINE_DATABASE_DSN`` from the environment.  The caller is
    responsible for closing the connection (prefer using a ``with`` block).
    """
    if dsn is None:
        dsn = os.environ.get("PIPELINE_DATABASE_DSN")
    if not dsn:
        raise ValueError("no database DSN configured")
    return psycopg2.connect(dsn)


def _serialize_optional(values: Sequence[object] | None) -> str | None:
    if values is None:
        return None
    # JSON preserves lists and floats; PostgreSQL arrays could also be used
    return json.dumps(list(values), ensure_ascii=False)


def ensure_schema(conn: psycopg2.extensions.connection) -> None:
    """Create the tables if they don't already exist.

    The production database does not store image binary data or file paths.
    The ``images`` table only records a numeric id and an optional
    ``username_hash``; the orchestrator is responsible for copying files to an
    external storage root and looking them up by id when analysis is needed.
    This keeps the PostgreSQL instance lean and avoids persisting sensitive
    file locations.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id SERIAL PRIMARY KEY,
                city TEXT NOT NULL,
                park TEXT NOT NULL,
                username_hash TEXT NOT NULL,
                comment TEXT,
                time TIMESTAMP,
                rating TEXT,
                sentiment_score REAL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS images (
                id SERIAL PRIMARY KEY,
                -- post_id may be null for orphaned uploads; the orchestrator
                -- will typically associate images with posts when importing
                -- CSV data.  leaving it nullable avoids insert failures when
                -- ingesting an image folder directly.
                post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
                username_hash TEXT
            );
            """
        )
        # additional tables for many‑to‑one species and activity entries
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS image_species (
                id SERIAL PRIMARY KEY,
                image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                species TEXT NOT NULL,
                confidence REAL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS image_activity (
                id SERIAL PRIMARY KEY,
                image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                activity TEXT NOT NULL
            );
            """
        )
    conn.commit()
    # ingestion tracking table – record filenames and progress so uploads can be
    # resumed or monitored.  created_at uses default now(); updated_at must be
    # set by callers.
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ingestion_status (
                id SERIAL PRIMARY KEY,
                filename TEXT UNIQUE,
                status TEXT,
                last_processed_row INTEGER,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP
            );
            """
        )
    conn.commit()


def insert_post(
    conn: psycopg2.extensions.connection,
    *,
    city: str,
    park: str,
    username: str,
    username_hash: str,
    comment: str | None,
    time: str | None,
    rating: str | None,
    sentiment_score: float | None = None,
) -> int:
    """Insert a post row and return the new primary key.

    ``username_hash`` is stored for privacy when the data is exported to
    downstream systems. ``username`` is accepted but not stored in Postgres.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO posts (city, park, username_hash, comment, time, rating, sentiment_score)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (city, park, username_hash, comment, time, rating, sentiment_score),
        )
        post_id = cur.fetchone()[0]
    conn.commit()
    return post_id





def fetch_posts_for_sentiment(
    conn: psycopg2.extensions.connection, limit: int
) -> list[tuple[int, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, COALESCE(comment, '')
            FROM posts
            WHERE sentiment_score IS NULL
            ORDER BY id
            LIMIT %s
            """,
            (limit,)
        )
        return [(int(r[0]), str(r[1])) for r in cur.fetchall()]


# image helpers ------------------------------------------------------------

def insert_image(
    conn: psycopg2.extensions.connection,
    *,
    post_id: int | None,
    path: str,
    username_hash: str | None = None,
) -> int:
    """Insert an image record and return its id.

    ``post_id`` may be ``None`` when the image is uploaded standalone; the
    database now permits null values for this column. ``username_hash`` may be
    derived from the filename so downstream analysis can link back to the
    origin. ``path`` is accepted but not stored in Postgres.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO images (post_id, username_hash)
            VALUES (%s, %s)
            RETURNING id
            """,
            (post_id, username_hash),
        )
        image_id = cur.fetchone()[0]
    conn.commit()
    return image_id


def fetch_unanalyzed_images(
    conn: psycopg2.extensions.connection, limit: int
) -> list[tuple[int, str | None]]:
    """Return (id, username_hash) tuples for rows without species data yet.

    Because species information now lives in a separate table, we select
    images that have *no* corresponding rows in ``image_species``.  The
    returned username_hash may be ``None``.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.id, i.username_hash
            FROM images AS i
            LEFT JOIN image_species AS s ON s.image_id = i.id
            WHERE s.id IS NULL
            ORDER BY i.id
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [(int(r[0]), r[1]) for r in rows]


def update_image_analysis(
    conn: psycopg2.extensions.connection,
    *,
    image_id: int,
    species: Sequence[str] | None,
    confidence: Sequence[float] | None,
) -> None:
    """Replace the species/confidence rows for an image.

    The values are stored in the ``image_species`` table; existing entries
    for the given ``image_id`` are deleted before the new ones are inserted.
    """
    if species is None:
        species = []
    if confidence is None:
        confidence = []
    with conn.cursor() as cur:
        # remove any prior tags
        cur.execute("DELETE FROM image_species WHERE image_id = %s", (image_id,))
        # insert new rows
        for sp, conf in zip(species, confidence):
            cur.execute(
                "INSERT INTO image_species (image_id, species, confidence) VALUES (%s, %s, %s)",
                (image_id, sp, conf),
            )
    conn.commit()


def update_image_activity(
    conn: psycopg2.extensions.connection,
    *,
    image_id: int,
    activity: str,
) -> None:
    """Append an activity record for a given image.

    Multiple activities may be associated with the same image; each call
    inserts a new row into ``image_activity``.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO image_activity (image_id, activity) VALUES (%s, %s)",
            (image_id, activity),
        )
    conn.commit()


# ingestion status helpers --------------------------------------------------

def upsert_ingestion_status(
    conn: psycopg2.extensions.connection,
    *,
    filename: str,
    status: str,
    last_processed_row: int | None = None,
) -> None:
    """Insert or update a row in the ``ingestion_status`` table.

    ``status`` should be one of ``pending``, ``processing``, ``done``,
    ``failed``.  ``last_processed_row`` is optional and indicates how far the
    import progressed.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_status (filename, status, last_processed_row, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (filename) DO UPDATE
            SET status = EXCLUDED.status,
                last_processed_row = EXCLUDED.last_processed_row,
                updated_at = NOW()
            """,
            (filename, status, last_processed_row),
        )
    conn.commit()


def get_ingestion_status(
    conn: psycopg2.extensions.connection, filename: str
) -> tuple[int, str, int | None, str | None, str | None] | None:
    """Return the ingestion_status row for ``filename`` or ``None``.

    The tuple returned is `(id, filename, last_processed_row, created_at,
    updated_at)`.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, filename, last_processed_row, created_at, updated_at"
            " FROM ingestion_status WHERE filename = %s",
            (filename,),
        )
        row = cur.fetchone()
    return None if row is None else (row[0], row[1], row[2], row[3], row[4])
