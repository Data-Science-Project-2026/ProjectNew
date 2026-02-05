from __future__ import annotations

import io
import math
import sqlite3
import textwrap
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
from matplotlib import font_manager
FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
cjk_font = font_manager.FontProperties(fname=FONT_PATH)

from PIL import Image

from src.database import sql


def load_post_with_images(
    post_id: int, db_path: str = "data.db"
) -> Tuple[Dict[str, str | None], List[Image.Image]]:
    """Fetch post metadata plus Pillow images via a posts/images join."""

    with sqlite3.connect(db_path) as conn:
        sql.ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT p.location, p.username, p.comment, p.time, p.rating, i.image
            FROM posts AS p
            LEFT JOIN images AS i ON p.id = i.post_id
            WHERE p.id = ?
            ORDER BY i.id
            """,
            (post_id,),
        ).fetchall()

    if not rows:
        raise ValueError(f"Post {post_id} was not found in the database.")

    metadata = {
        "location": rows[0][0],
        "username": rows[0][1],
        "comment": rows[0][2],
        "time": rows[0][3],
        "rating": rows[0][4],
    }

    images: List[Image.Image] = []
    for _, _, _, _, _, blob in rows:
        if blob is None:
            continue
        try:
            image = Image.open(io.BytesIO(blob)).convert("RGB")
            images.append(image)
        except Exception as exc:  # pragma: no cover - defensive logging only
            print(f"Skipping unreadable image for post {post_id}: {exc}")

    return metadata, images


def _format_metadata_block(metadata: Dict[str, str | None], comment_text: str) -> str:
    lines = [
        f"Location: {metadata['location']}",
        f"User: {metadata['username']}",
        f"Rating: {metadata['rating'] or 'N/A'}",
        f"Time: {metadata['time'] or 'N/A'}",
        "",
        "Comment:",
        comment_text,
    ]
    return "\n".join(lines)


def _print_copyable_metadata(text: str) -> None:
    separator = "-" * 40
    print(f"\n{separator}\nPost metadata (copy/paste)\n{separator}\n{text}\n{separator}\n")


def render_post(post_id: int, db_path: str = "data.db") -> List[Image.Image]:
    """Load and render post details with all associated images."""

    try:
        metadata, images = load_post_with_images(post_id, db_path=db_path)
    except ValueError as exc:
        print(exc)
        return []

    if images:
        cols = min(3, len(images))
        rows = math.ceil(len(images) / cols)
    else:
        rows = cols = 1

    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 4 * rows))

    if isinstance(axes, plt.Axes):
        flat_axes = [axes]
    else:
        flat_axes = list(axes.flat)

    if images:
        for ax, image in zip(flat_axes, images):
            ax.imshow(image)
            ax.axis("off")
        for ax in flat_axes[len(images) :]:
            ax.axis("off")
    else:
        ax = flat_axes[0]
        ax.axis("off")
        ax.text(0.5, 0.5, "No images available", ha="center", va="center", fontsize=12, fontproperties=cjk_font)

    comment_text = metadata["comment"] or "(no comment provided)"
    wrapped_comment = textwrap.fill(comment_text, width=90)
    metadata_header = (
        f"Location: {metadata['location']} | User: {metadata['username']} | "
        f"Rating: {metadata['rating'] or 'N/A'}\n"
        f"Time: {metadata['time'] or 'N/A'}\n"
        f"Comment: {wrapped_comment}"
    )
    fig.suptitle(metadata_header, fontsize=11, fontproperties=cjk_font, y=0.98)
    fig.subplots_adjust(top=0.78, bottom=0.06)

    fig.tight_layout(rect=(0, 0.07, 1, 0.92))
    plt.show()

    metadata_text = _format_metadata_block(metadata, comment_text)
    _print_copyable_metadata(metadata_text)
    return images


if __name__ == "__main__":
    import argparse

    # For example, use python3 src/database/load_image_from_db.py 4 --db data.db
    parser = argparse.ArgumentParser(description="Render images stored in the database for a post.")
    parser.add_argument("post_id", type=int, help="ID of the post to render images for")
    parser.add_argument("--db", dest="db_path", default="data.db", help="Path to the SQLite database")
    args = parser.parse_args()

    render_post(args.post_id, db_path=args.db_path)
