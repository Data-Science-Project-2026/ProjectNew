from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import sqlite3
import re

from src.database import sql

_FILENAME_COLUMN = "图像文件名列表"
# Columns: "Username", "Comment", "Timestamp", "Rating", "Image Filename List"
_REQUIRED_COLUMNS: Sequence[str] = ("用户名", "评论", "时间", "评分", _FILENAME_COLUMN)


@dataclass
class CsvPostRow:
    username: str
    comment: str | None
    timestamp: str | None
    rating: str | None
    image_filenames: List[str]


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _parse_image_filenames(value: str | None) -> List[str]:
    text = _normalize_text(value)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]

    normalized = text
    for sep in ("|", ",", ";"):
        normalized = normalized.replace(sep, ";")
    return [chunk.strip() for chunk in normalized.split(";") if chunk.strip()]


def _iter_csv_rows(csv_file: Path) -> Iterable[CsvPostRow]:
    with csv_file.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file is missing a header row.")

        missing = [column for column in _REQUIRED_COLUMNS if column not in reader.fieldnames]
        if missing:
            raise ValueError(f"CSV file is missing required columns: {', '.join(missing)}")

        for row in reader:
            username = _normalize_text(row.get("用户名"))
            if username is None:
                continue

            comment = _normalize_text(row.get("评论"))
            timestamp = _normalize_text(row.get("时间"))
            rating = _normalize_text(row.get("评分"))
            image_filenames = _parse_image_filenames(row.get(_FILENAME_COLUMN))
            yield CsvPostRow(username, comment, timestamp, rating, image_filenames)


def _build_image_lookup(folder: Path) -> Dict[str, Path]:
    lookup: Dict[str, Path] = {}
    for class_dir in folder.glob("class_*"):
        if not class_dir.is_dir():
            continue
        for image_path in class_dir.rglob("*"):
            if image_path.is_file():
                lookup.setdefault(image_path.name, image_path)
    return lookup


def _resolve_image_path(filename: str, lookup: Dict[str, Path]) -> Path | None:
    path = lookup.get(Path(filename).name)
    if path is None or not path.is_file():
        return None
    return path


def _locate_csv_file(folder: Path) -> Path:
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")

    preferred = folder / f"{folder.name}.csv"
    if preferred.is_file():
        return preferred

    candidates = list(folder.glob("*.csv"))
    if not candidates:
        raise FileNotFoundError(f"No CSV files were found in {folder}")
    if len(candidates) == 1:
        return candidates[0]

    raise ValueError(
        "Multiple CSV files found. Please ensure one matches the folder name or remove extras."
    )


def import_posts_and_images_from_folder(folder_path: str, city: str, db_path: str = "data.db") -> tuple[int, int]:
    """Insert posts and their images from a folder containing a CSV and class_* images.

    Returns a tuple of (post_count, image_count).
    """

    folder = Path(folder_path)
    csv_file = _locate_csv_file(folder)

    image_lookup = _build_image_lookup(folder)
    # Park name: remove leading digits from the CSV stem, then remove the city string
    park_stem = re.sub(r"^\d+", "", csv_file.stem)
    if park_stem.startswith(city):
        park = park_stem[len(city) :]
    else:
        park = park_stem

    post_count = 0
    image_count = 0

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        sql.ensure_schema(conn)

        for row in _iter_csv_rows(csv_file):
            post_id = sql.insert_post(
                conn,
                city=city,
                park=park,
                username=row.username,
                comment=row.comment,
                time=row.timestamp,
                rating=row.rating,
            )
            post_count += 1

            for filename in row.image_filenames:
                image_path = _resolve_image_path(filename, image_lookup)
                if image_path is None:
                    continue

                image_blob = image_path.read_bytes()
                sql.insert_image(conn, post_id=post_id, image=image_blob)
                image_count += 1

        conn.commit()

    return post_count, image_count


def import_posts_and_images_from_all_folders(
    parent_folder: str, db_path: str = "data.db"
) -> List[Tuple[str, int, int]]:
    """Run imports for child folders. Folders must have 1 csv file, and class folders (images)"""

    parent = Path(parent_folder)
    if not parent.is_dir():
        raise FileNotFoundError(f"Folder not found: {parent}")
    # Parse city from the parent folder name: number + city + underscore
    # e.g. '6深圳_携程图像文本' -> city == '深圳'
    parent_name = parent.name
    m = re.match(r"^\d+([^_]+)_", parent_name)
    if not m:
        raise ValueError(f"Unable to parse city name from parent folder: {parent_name}")
    city = m.group(1)

    results: List[Tuple[str, int, int]] = []
    for child in sorted(parent.iterdir()):
        if not child.is_dir():
            continue

        csv_files = [p for p in child.glob("*.csv") if p.is_file()]
        if len(csv_files) != 1:
            continue

        class_dirs = [p for p in child.glob("class_*") if p.is_dir()]
        if len(class_dirs) < 2:
            continue

        try:
            _locate_csv_file(child)
        except (FileNotFoundError, ValueError):
            continue

        posts, images = import_posts_and_images_from_folder(str(child), city=city, db_path=db_path)
        results.append((child.name, posts, images))

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import posts and images from data folders into a SQLite database.")
    parser.add_argument("folder", nargs="?", default="6深圳_携程图像文本", help="Parent folder containing location subfolders (default: 6深圳_携程图像文本)")
    parser.add_argument("--db", dest="db_path", default="data.db", help="Path to SQLite database (default: data.db)")
    args = parser.parse_args()

    results = import_posts_and_images_from_all_folders(args.folder, db_path=args.db_path)
    for folder_name, posts, images in results:
        print(f"Imported {posts} posts and {images} images from {folder_name}")