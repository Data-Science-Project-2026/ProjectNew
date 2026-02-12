from __future__ import annotations

import json
import sqlite3
from typing import Sequence


POST_COLUMNS = [
    ("id", "INTEGER"),
    ("location", "TEXT"),
    ("username", "TEXT"),
    ("comment", "TEXT"),
    ("time", "TEXT"),
    ("rating", "TEXT"),
    ("sentiment_score", "REAL"),
]


def _ensure_posts_table(conn: sqlite3.Connection) -> None:
    """Ensure the posts table exists with the expected schema."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            location TEXT NOT NULL,
            username TEXT NOT NULL,
            comment TEXT,
            time TEXT,
            rating TEXT,
            sentiment_score REAL
        )
        """
    )
    existing_columns = [row[1] for row in conn.execute("PRAGMA table_info(posts)")]
    expected = [name for name, _ in POST_COLUMNS]
    if existing_columns != expected:
        conn.execute("DROP TABLE IF EXISTS posts")
        conn.execute(
            """
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                location TEXT NOT NULL,
                username TEXT NOT NULL,
                comment TEXT,
                time TEXT,
                rating TEXT,
                sentiment_score REAL
            )
            """
        )


IMAGE_COLUMNS = [
    ("id", "INTEGER"),
    ("post_id", "INTEGER"),
    ("image", "BLOB"),
    ("species", "TEXT"),
    ("confidence", "TEXT"),
    ("activity", "TEXT"),
]


def _ensure_images_table(conn: sqlite3.Connection) -> None:
    """Ensure the images table exists with the expected schema."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            image BLOB NOT NULL,
            species TEXT,
            confidence TEXT,
            activity TEXT,
            FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
        )
        """
    )
    existing_columns = [row[1] for row in conn.execute("PRAGMA table_info(images)")]
    expected = [name for name, _ in IMAGE_COLUMNS]
    if existing_columns != expected:
        conn.execute("DROP TABLE IF EXISTS images")
        conn.execute(
            """
            CREATE TABLE images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL,
                image BLOB NOT NULL,
                species TEXT,
                confidence TEXT,
                activity TEXT,
                FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
            )
            """
        )


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Ensure that both posts and images tables exist with the expected schema."""
    _ensure_posts_table(conn)
    _ensure_images_table(conn)


def insert_post(
    conn: sqlite3.Connection,
    *,
    location: str,
    username: str,
    comment: str | None,
    time: str | None,
    rating: str | None,
    sentiment_score: float | None = None,
) -> int:
    """Insert a single post record and return its primary key."""
    _ensure_posts_table(conn)
    cursor = conn.execute(
        """
        INSERT INTO posts (location, username, comment, time, rating, sentiment_score)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (location, username, comment, time, rating, sentiment_score),
    )
    return int(cursor.lastrowid)


def _serialize_optional(values: Sequence[object] | None) -> str | None:
    if values is None:
        return None
    return json.dumps(list(values), ensure_ascii=False)


def insert_image(
    conn: sqlite3.Connection,
    *,
    post_id: int,
    image: bytes,
    species: Sequence[str] | None = None,
    confidence: Sequence[float] | None = None,
    activity: str | None = None,
) -> int:
    """Insert a single image row linked to a post."""
    _ensure_images_table(conn)
    cursor = conn.execute(
        """
        INSERT INTO images (post_id, image, species, confidence, activity)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            post_id,
            image,
            _serialize_optional(species),
            _serialize_optional(confidence),
            activity,
        ),
    )
    return int(cursor.lastrowid)


def fetch_images_for_post(conn: sqlite3.Connection, post_id: int) -> list[bytes]:
    """Return all image blobs associated with the provided post id."""
    _ensure_images_table(conn)
    rows = conn.execute(
        "SELECT image FROM images WHERE post_id=? ORDER BY id",
        (post_id,),
    ).fetchall()
    return [row[0] for row in rows]


def fetch_unanalyzed_images(
    conn: sqlite3.Connection, limit: int
) -> list[tuple[int, bytes]]:
    """Fetch image ids and blobs that do not have species/confidence yet."""
    _ensure_images_table(conn)
    rows = conn.execute(
        """
        SELECT id, image
        FROM images
        WHERE species IS NULL AND confidence IS NULL
        ORDER BY id
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    return [(int(row[0]), row[1]) for row in rows]


def update_image_analysis(
    conn: sqlite3.Connection,
    *,
    image_id: int,
    species: Sequence[str] | None,
    confidence: Sequence[float] | None,
) -> None:
    """Update species/confidence fields for a specific image row."""
    _ensure_images_table(conn)
    conn.execute(
        """
        UPDATE images
        SET species = ?, confidence = ?
        WHERE id = ?
        """,
        (_serialize_optional(species), _serialize_optional(confidence), int(image_id)),
    )


def _human_readable_bytes(num_bytes: int | None) -> str:
    if not num_bytes:
        return "0 B"
    value = float(num_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} PB"


def print_database_summary(db_path: str = "data.db") -> None:
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        post_count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        image_count = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]

        post_bytes = conn.execute(
            """
            SELECT SUM(
                COALESCE(LENGTH(location), 0) +
                COALESCE(LENGTH(username), 0) +
                COALESCE(LENGTH(comment), 0) +
                COALESCE(LENGTH(time), 0) +
                COALESCE(LENGTH(rating), 0)
            ) FROM posts
            """
        ).fetchone()[0]

        image_bytes = conn.execute(
            "SELECT SUM(LENGTH(image)) FROM images"
        ).fetchone()[0]

    total_bytes = (post_bytes or 0) + (image_bytes or 0)
    print("Database Summary:")
    print(f"  Posts: {post_count} rows (~{_human_readable_bytes(post_bytes)})")
    print(f"  Images: {image_count} rows (~{_human_readable_bytes(image_bytes)})")
    print(f"  Approx storage for row data: {_human_readable_bytes(total_bytes)}")
    print()

def _print_table_schema(conn: sqlite3.Connection, table: str) -> None:
    create_stmt = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    print(f"Schema for `{table}`:")
    if create_stmt and create_stmt[0]:
        print(create_stmt[0])
    else:
        print("  (no CREATE TABLE statement found)")
    print("Columns:")
    for cid, name, col_type, notnull, default, pk in conn.execute(f"PRAGMA table_info({table})"):
        print(
            f"  - {cid}: {name} ({col_type}) "
            f"NOT NULL={bool(notnull)} DEFAULT={default} PK={bool(pk)}"
        )
    print()


def print_table_schemas(db_path: str = "data.db") -> None:
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        for table in ("posts", "images"):
            _print_table_schema(conn, table)

if __name__ == "__main__":
    print_database_summary()
    print_table_schemas()