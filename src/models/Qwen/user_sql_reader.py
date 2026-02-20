from __future__ import annotations

import argparse
import base64
import sqlite3
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Set, Tuple


@dataclass(frozen=True)
class QwenImageInput:
    image_id: int
    post_id: int
    data_url: str


@dataclass(frozen=True)
class QwenUserBatchInput:
    city: str
    park: str
    username: str
    post_ids: List[int]
    comments: List[str]
    images: List[QwenImageInput]

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


def _build_where_clause(city: str | None, park: str | None, username: str | None) -> tuple[str, list[str]]:
    clauses: list[str] = ["i.image IS NOT NULL"]
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

    Group key is (city, park, username), so users with the same name in different parks
    are kept separate.
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
            i.image AS image_blob
        FROM posts AS p
        JOIN images AS i ON i.post_id = p.id
        WHERE {where_sql}
        ORDER BY p.city, p.park, p.username, p.id, i.id
    """

    grouped: dict[tuple[str, str, str], _GroupBucket] = {}

    with sqlite3.connect(db_path) as conn:
        _assert_required_tables(conn)
        rows = conn.execute(query, params).fetchall()

    for row in rows:
        post_id = int(row[0])
        city_value = str(row[1])
        park_value = str(row[2])
        username_value = str(row[3])
        comment_value = str(row[4]) if row[4] is not None else ""
        image_id = int(row[5])
        image_blob = bytes(row[6])

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

        seen_posts = bucket.seen_posts
        if post_id not in seen_posts:
            bucket.post_ids.append(post_id)
            seen_posts.add(post_id)

        normalized_comment = comment_value.strip()
        if normalized_comment:
            seen_comments = bucket.seen_comments
            comment_key = (post_id, normalized_comment)
            if comment_key not in seen_comments:
                bucket.comments.append(normalized_comment)
                seen_comments.add(comment_key)

        bucket.images.append(
            QwenImageInput(
                image_id=image_id,
                post_id=post_id,
                data_url=_blob_to_data_url(image_blob),
            )
        )

    batches: list[QwenUserBatchInput] = []
    for (city_value, park_value, username_value), bucket in grouped.items():
        images: Sequence[QwenImageInput] = bucket.images
        if len(images) < int(min_images):
            continue

        batches.append(
            QwenUserBatchInput(
                city=city_value,
                park=park_value,
                username=username_value,
                post_ids=list(bucket.post_ids),
                comments=list(bucket.comments),
                images=list(images),
            )
        )

    return batches


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
