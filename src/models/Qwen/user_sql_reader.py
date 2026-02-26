from __future__ import annotations

import argparse
import base64
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Set, Tuple


@dataclass(frozen=True)
class QwenImageInput:
    image_id: int
    post_id: int
    data_url: str

    def to_dict(self) -> dict:
        return {"image_id": self.image_id, "post_id": self.post_id, "data_url": self.data_url}

    @staticmethod
    def from_dict(d: dict) -> "QwenImageInput":
        return QwenImageInput(
            image_id=d["image_id"],
            post_id=d["post_id"],
            data_url=d["data_url"],
        )


@dataclass(frozen=True)
class QwenUserBatchInput:
    city: str
    park: str
    username: str
    post_ids: List[int]
    comments: List[str]
    images: List[QwenImageInput]

    def to_dict(self) -> dict:
        return {
            "city": self.city,
            "park": self.park,
            "username": self.username,
            "post_ids": self.post_ids,
            "comments": self.comments,
            "images": [img.to_dict() for img in self.images],
        }

    @staticmethod
    def from_dict(d: dict) -> "QwenUserBatchInput":
        return QwenUserBatchInput(
            city=d["city"],
            park=d["park"],
            username=d["username"],
            post_ids=d["post_ids"],
            comments=d["comments"],
            images=[QwenImageInput.from_dict(img) for img in d["images"]],
        )

    def merged_comment(self, sep: str = "\n") -> str:
        return sep.join(comment for comment in self.comments if comment.strip())


@dataclass
class _GroupBucket:
    post_ids: List[int]
    comments: List[str]
    images: List[QwenImageInput]
    seen_posts: Set[int]
    seen_comments: Set[Tuple[int, str]]


def _blob_to_data_url(image_blob: bytes) -> str:
    encoded = base64.b64encode(image_blob).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def _read_image_file(path: str) -> bytes:
    """Read a binary image from disk; path may be relative or absolute."""
    p = Path(path)
    if not p.is_absolute():
        # assume current working directory or caller will supply root
        pass
    try:
        with open(p, "rb") as f:
            return f.read()
    except Exception:
        return b""


def _build_where_clause(city: str | None, park: str | None, username: str | None) -> tuple[str, list[str]]:
    clauses: list[str] = ["i.path IS NOT NULL"]
    params: list[str] = []

    if city:
        clauses.append("p.city = ?")
        params.append(city)
    if park:
        clauses.append("p.park = ?")
        params.append(park)
    if username:
        clauses.append("p.username = ?")
        params.append(username)

    return " AND ".join(clauses), params


def _assert_required_tables(conn: sqlite3.Connection) -> None:
    existing = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    required = {"posts", "images"}
    missing = sorted(required - existing)
    if missing:
        missing_str = ", ".join(missing)
        raise ValueError(
            f"Database is missing required table(s): {missing_str}. "
            "Run data import first (csv_to_sql.py)."
        )


def build_qwen_user_batches(
    db_path: str,
    *,
    city: str | None = None,
    park: str | None = None,
    username: str | None = None,
    min_images: int = 1,
) -> List[QwenUserBatchInput]:
    """Read SQL rows and aggregate them as Qwen-ready user batches.

    ``db_path`` is the path to a **SQLite** database file.  This helper exists
    for backwards compatibility with the original command‑line tools.  it is
    mostly a thin wrapper around :func:`build_qwen_user_batches_from_conn`.
    """

    where_sql, params = _build_where_clause(city, park, username)
    query = f"""
        SELECT
            p.id AS post_id,
            p.city,
            p.park,
            p.username,
            COALESCE(p.comment, '') AS comment,
            i.id AS image_id,
            i.path AS image_path
        FROM posts AS p
        JOIN images AS i ON i.post_id = p.id
        WHERE {where_sql}
        ORDER BY p.city, p.park, p.username, p.id, i.id
    """

    grouped: dict[tuple[str, str, str], _GroupBucket] = {}

    with sqlite3.connect(db_path) as conn:
        _assert_required_tables(conn)
        rows = conn.execute(query, params).fetchall()

    # delegate the heavy lifting to the connection-agnostic helper below
    return _batches_from_rows(rows, min_images)


# new helper that accepts raw rows (generic sequence) and can be reused by
# both SQLite and Postgres callers.

def _batches_from_rows(rows: Iterable[Sequence], min_images: int, max_images: int = 0) -> List[QwenUserBatchInput]:
    """Build batches from rows.  If *max_images* > 0, cap images per batch."""
    grouped: dict[tuple[str, str, str], _GroupBucket] = {}

    for row in rows:
        post_id = int(row[0])
        city_value = str(row[1])
        park_value = str(row[2])
        username_value = str(row[3])
        comment_value = str(row[4]) if row[4] is not None else ""
        image_id = int(row[5])
        image_path = str(row[6])


        key = (city_value, park_value, username_value)
        bucket = grouped.setdefault(
            key,
            _GroupBucket(
                post_ids=[],
                comments=[],
                images=[],
                seen_posts=set(),
                seen_comments=set(),
            ),
        )

        if post_id not in bucket.seen_posts:
            bucket.post_ids.append(post_id)
            bucket.seen_posts.add(post_id)

        normalized_comment = comment_value.strip()
        if normalized_comment:
            comment_key = (post_id, normalized_comment)
            if comment_key not in bucket.seen_comments:
                bucket.comments.append(normalized_comment)
                bucket.seen_comments.add(comment_key)

        bucket.images.append(
            QwenImageInput(
                image_id=image_id,
                post_id=post_id,
                data_url=_blob_to_data_url(_read_image_file(image_path)),
            )
        )

    batches: list[QwenUserBatchInput] = []
    for (city_value, park_value, username_value), bucket in grouped.items():
        if len(bucket.images) < int(min_images):
            continue
        imgs = list(bucket.images)
        if max_images > 0 and len(imgs) > max_images:
            imgs = imgs[:max_images]
        batches.append(
            QwenUserBatchInput(
                city=city_value,
                park=park_value,
                username=username_value,
                post_ids=list(bucket.post_ids),
                comments=list(bucket.comments),
                images=imgs,
            )
        )
    return batches


def build_qwen_user_batches_pg(
    conn,
    *,
    city: str | None = None,
    park: str | None = None,
    username: str | None = None,
    min_images: int = 1,
    max_images: int = 0,
    image_root: str | None = None,
) -> List[QwenUserBatchInput]:
    """Same as :func:`build_qwen_user_batches` but works over a Postgres cursor.

    ``conn`` may be any PEP 249 connection object (including psycopg2).
    Postgres uses ``username_hash`` instead of ``username`` and stores
    optional ``path`` on images.  ``image_root`` is prepended to the
    stored path when reading image files from disk.
    """
    clauses: list[str] = ["i.path IS NOT NULL"]
    params: list[str] = []
    if city:
        clauses.append("p.city = %s")
        params.append(city)
    if park:
        clauses.append("p.park = %s")
        params.append(park)
    if username:
        clauses.append("p.username_hash = %s")
        params.append(username)
    where_sql = " AND ".join(clauses)

    query = f"""
        SELECT
            p.id AS post_id,
            p.city,
            p.park,
            p.username_hash,
            COALESCE(p.comment, '') AS comment,
            i.id AS image_id,
            i.path AS image_path
        FROM posts AS p
        JOIN images AS i ON i.post_id = p.id
        WHERE {where_sql}
        ORDER BY p.city, p.park, p.username_hash, p.id, i.id
    """

    cursor = conn.cursor()
    cursor.execute(query, params)
    rows = cursor.fetchall()

    # If image_root provided, prepend it to the path column (index 6)
    if image_root:
        adjusted = []
        for row in rows:
            r = list(row)
            r[6] = str(Path(image_root) / r[6])
            adjusted.append(tuple(r))
        rows = adjusted

    return _batches_from_rows(rows, min_images, max_images=max_images)


def build_qwen_messages(batch: QwenUserBatchInput, instruction: str) -> list[dict]:
    """Convert one batch to OpenAI-compatible messages payload."""

    user_content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"City: {batch.city}; Park: {batch.park}; User: {batch.username}.\n"
                f"Comments from this user:\n{batch.merged_comment()}"
            ),
        }
    ]

    for image in batch.images:
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": image.data_url},
            }
        )

    return [
        {"role": "system", "content": instruction},
        {"role": "user", "content": user_content},
    ]


def _print_preview(batches: Iterable[QwenUserBatchInput]) -> None:
    for batch in batches:
        print(
            f"city={batch.city} | park={batch.park} | user={batch.username} | "
            f"posts={len(batch.post_ids)} | comments={len(batch.comments)} | images={len(batch.images)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Qwen user-level multimodal batches from SQLite.")
    parser.add_argument("--db", dest="db_path", default="src/database/data.db", help="Path to SQLite DB")
    parser.add_argument("--city", default=None, help="Filter by city")
    parser.add_argument("--park", default=None, help="Filter by park")
    parser.add_argument("--username", default=None, help="Filter by username")
    parser.add_argument("--min-images", type=int, default=1, help="Keep only users with at least N images")
    args = parser.parse_args()

    try:
        batches = build_qwen_user_batches(
            args.db_path,
            city=args.city,
            park=args.park,
            username=args.username,
            min_images=args.min_images,
        )
    except ValueError as exc:
        print(exc)
        return

    print(f"Total batches: {len(batches)}")
    _print_preview(batches)


if __name__ == "__main__":
    main()
