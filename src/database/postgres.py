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
                sentiment_score REAL,
                bert_sentiment_score REAL,
                bert_sentiment_label TEXT,
                qwen_sentiment_score REAL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS images (
                id SERIAL PRIMARY KEY,
                post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
                username_hash TEXT,
                path TEXT
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
        # ── Qwen batch-level results ────────────────────────────────────
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS qwen_batch_results (
                id SERIAL PRIMARY KEY,
                city TEXT,
                park TEXT,
                username_hash TEXT,
                post_ids TEXT,
                raw_response TEXT,
                emotions TEXT,
                influence_of_emotions TEXT,
                text_species_mentions TEXT,
                feeling_correlated_to_text_species TEXT,
                text_activities_or_facilities TEXT,
                feeling_correlated_to_text_activities_or_facilities TEXT,
                comment_sentiment_score REAL,
                association_likelihood REAL,
                association_summary TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
            """
        )
        # ── Per-image detail from Qwen ──────────────────────────────────
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS image_qwen_detail (
                id SERIAL PRIMARY KEY,
                image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                batch_result_id INTEGER REFERENCES qwen_batch_results(id) ON DELETE SET NULL,
                image_summary TEXT,
                visible_species TEXT,
                landscape_elements TEXT,
                human_activities TEXT
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
    """Return posts that have not yet been scored by Bert."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, COALESCE(comment, '')
            FROM posts
            WHERE bert_sentiment_score IS NULL
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
            INSERT INTO images (post_id, username_hash, path)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (post_id, username_hash, path),
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


# ── sentiment helpers ─────────────────────────────────────────────────────

def update_post_sentiment(
    conn: psycopg2.extensions.connection,
    *,
    post_id: int,
    sentiment_score: float,
) -> None:
    """Set the legacy sentiment_score column for a post (kept for compatibility)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE posts SET sentiment_score = %s WHERE id = %s",
            (sentiment_score, post_id),
        )
    conn.commit()


def update_bert_sentiment(
    conn: psycopg2.extensions.connection,
    *,
    post_id: int,
    score: float,
    label: str,
) -> None:
    """Write Bert sentiment analysis result independently."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE posts SET bert_sentiment_score = %s, bert_sentiment_label = %s WHERE id = %s",
            (score, label, post_id),
        )
    conn.commit()


def update_qwen_sentiment(
    conn: psycopg2.extensions.connection,
    *,
    post_id: int,
    score: float,
) -> None:
    """Write Qwen sentiment analysis result independently."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE posts SET qwen_sentiment_score = %s WHERE id = %s",
            (score, post_id),
        )
    conn.commit()


# ── Qwen batch result helpers ────────────────────────────────────────────

def insert_qwen_batch_result(
    conn: psycopg2.extensions.connection,
    *,
    city: str,
    park: str,
    username_hash: str,
    post_ids: list[int],
    raw_response: str,
    emotions: list[str] | None = None,
    influence_of_emotions: str | None = None,
    text_species_mentions: list | str | None = None,
    feeling_correlated_to_text_species: list | str | None = None,
    text_activities_or_facilities: list | str | None = None,
    feeling_correlated_to_text_activities_or_facilities: list | str | None = None,
    comment_sentiment_score: float | None = None,
    association_likelihood: float | None = None,
    association_summary: str | None = None,
) -> int:
    """Insert one Qwen batch result row and return its id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO qwen_batch_results (
                city, park, username_hash, post_ids, raw_response,
                emotions, influence_of_emotions,
                text_species_mentions, feeling_correlated_to_text_species,
                text_activities_or_facilities,
                feeling_correlated_to_text_activities_or_facilities,
                comment_sentiment_score,
                association_likelihood, association_summary
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s,
                %s, %s
            ) RETURNING id
            """,
            (
                city, park, username_hash,
                json.dumps(post_ids),
                raw_response,
                json.dumps(emotions) if emotions else None,
                influence_of_emotions,
                json.dumps(text_species_mentions) if isinstance(text_species_mentions, list) else text_species_mentions,
                json.dumps(feeling_correlated_to_text_species) if isinstance(feeling_correlated_to_text_species, list) else feeling_correlated_to_text_species,
                json.dumps(text_activities_or_facilities) if isinstance(text_activities_or_facilities, list) else text_activities_or_facilities,
                json.dumps(feeling_correlated_to_text_activities_or_facilities) if isinstance(feeling_correlated_to_text_activities_or_facilities, list) else feeling_correlated_to_text_activities_or_facilities,
                comment_sentiment_score,
                association_likelihood, association_summary,
            ),
        )
        batch_id = cur.fetchone()[0]
    conn.commit()
    return batch_id


def insert_image_qwen_detail(
    conn: psycopg2.extensions.connection,
    *,
    image_id: int,
    batch_result_id: int | None = None,
    image_summary: str | None = None,
    visible_species: list | None = None,
    landscape_elements: list | None = None,
    human_activities: list | None = None,
) -> int:
    """Insert a per-image Qwen detail row."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO image_qwen_detail (
                image_id, batch_result_id,
                image_summary, visible_species, landscape_elements, human_activities
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                image_id, batch_result_id,
                image_summary,
                json.dumps(visible_species) if isinstance(visible_species, list) else None,
                json.dumps(landscape_elements) if isinstance(landscape_elements, list) else None,
                json.dumps(human_activities) if isinstance(human_activities, list) else None,
            ),
        )
        detail_id = cur.fetchone()[0]
    conn.commit()
    return detail_id


def fetch_qwen_batch_results(
    conn: psycopg2.extensions.connection,
    *,
    city: str | None = None,
    park: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Return recent Qwen batch results as dicts for dashboard queries."""
    clauses = ["1=1"]
    params: list = []
    if city:
        clauses.append("city = %s")
        params.append(city)
    if park:
        clauses.append("park = %s")
        params.append(park)
    params.append(limit)
    where = " AND ".join(clauses)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, city, park, username_hash, post_ids, raw_response,
                   emotions, influence_of_emotions, comment_sentiment_score,
                   association_likelihood, association_summary, created_at
            FROM qwen_batch_results
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            params,
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
