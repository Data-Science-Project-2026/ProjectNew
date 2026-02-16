from __future__ import annotations

import shutil
from pathlib import Path
import sqlite3
import time
from typing import Optional


def strip_db_images(src_db: str, dest_db: Optional[str] = None) -> str:
    """Create a copy of `src_db` with the `image` column in `images` nulled out.

    Returns the path to the new database file.
    If `dest_db` is omitted, a new filename is created by appending
    `_noimages` before the original suffix (e.g. `data.db` -> `data_noimages.db`).
    """
    src = Path(src_db)
    if dest_db is None:
        dest = src.with_name(f"{src.stem}_noimages{src.suffix}")
    else:
        dest = Path(dest_db)

    # Copy the file first (preserves schema and other data)
    shutil.copy2(src, dest)

    # Open the copied DB and remove blobs from images.image (if present)
    conn = sqlite3.connect(dest)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.cursor()

        # Check whether images table and image column exist
        try:
            cols = [row[1] for row in cur.execute("PRAGMA table_info(images)")]
        except sqlite3.OperationalError:
            cols = []

        if "image" in cols:
            # Replace the blob column with an empty blob (can't set NULL due to NOT NULL)
            cur.execute("UPDATE images SET image = X'' WHERE image IS NOT NULL")
            conn.commit()

            # VACUUM the DB to reclaim space
            # VACUUM can be slow for large DBs; keep it but it's useful to shrink file size.
            cur.execute("VACUUM")
            conn.commit()
        else:
            # No image column present; nothing to do beyond the copy
            pass
    finally:
        conn.close()

    return str(dest)


if __name__ == "__main__":
    # Default behaviour: strip images from data.db in the current working directory
    src = "src/database/data.db"
    print(f"Creating no-image copy of {src}...")
    start = time.time()
    out = strip_db_images(src)
    elapsed = time.time() - start
    print(f"Wrote stripped DB to: {out} ({elapsed:.1f}s)")
