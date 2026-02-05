from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from src.database import csv_to_sql

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FOLDER_PATH = PROJECT_ROOT / "6深圳_携程图像文本" / "2深圳市盐田区大梅沙海滨公园"
TARGET_ROW_INDEX = 4  # 1-based index over rows that contain a username


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _get_csv_path(folder: Path) -> Path:
    return csv_to_sql._locate_csv_file(folder)


def _count_valid_post_rows(csv_path: Path) -> int:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return sum(1 for row in reader if _normalize_text(row.get("用户名")))


def _count_images_in_folder(folder: Path) -> int:
    count = 0
    for class_dir in folder.glob("class_*"):
        if not class_dir.is_dir():
            continue
        for image_path in class_dir.rglob("*"):
            if image_path.is_file():
                count += 1
    return count


def _get_nth_valid_row(csv_path: Path, index: int) -> dict:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        valid_idx = 0
        for row in reader:
            if _normalize_text(row.get("用户名")) is None:
                continue
            valid_idx += 1
            if valid_idx == index:
                return row
    raise AssertionError(f"Valid row {index} not found in {csv_path}")


def _get_post_row_by_index(conn: sqlite3.Connection, index: int) -> sqlite3.Row:
    return conn.execute(
        "SELECT id, location, username, comment, time, rating FROM posts ORDER BY id LIMIT 1 OFFSET ?",
        (index - 1,),
    ).fetchone()


def test_folder_import_persists_posts_and_images(tmp_path) -> None:
    db_path = tmp_path / "integration.db"
    csv_path = _get_csv_path(FOLDER_PATH)

    post_count, image_count = csv_to_sql.import_posts_and_images_from_folder(
        str(FOLDER_PATH), db_path=str(db_path)
    )

    assert post_count == _count_valid_post_rows(csv_path)
    images_on_disk = _count_images_in_folder(FOLDER_PATH)
    assert image_count == images_on_disk

    expected_row = _get_nth_valid_row(csv_path, TARGET_ROW_INDEX)
    expected_username = _normalize_text(expected_row.get("用户名"))
    expected_comment = _normalize_text(expected_row.get("评论"))
    expected_time = _normalize_text(expected_row.get("时间"))
    expected_rating = _normalize_text(expected_row.get("评分"))

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        post_row = _get_post_row_by_index(conn, TARGET_ROW_INDEX)
        assert post_row is not None

        images_in_db = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]

    print("db_path:", db_path)
    print("post_count:", post_count)
    print("image_count:", image_count)
    print("target_row_index:", TARGET_ROW_INDEX)
    print("expected_username:", expected_username)
    print("expected_comment:", expected_comment)
    print("expected_time:", expected_time)
    print("expected_rating:", expected_rating)
    print("posts_table_row:", dict(post_row))
    print("images_in_db:", images_in_db)
    print("images_in_folder:", images_on_disk)

    assert post_row["location"] == csv_path.stem
    assert post_row["username"] == expected_username
    assert post_row["comment"] == expected_comment
    assert post_row["time"] == expected_time
    assert post_row["rating"] == expected_rating
    assert images_in_db == images_on_disk
