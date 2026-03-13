#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


TABLES: dict[str, dict[str, object]] = {
    "posts": {
        "select": """
            SELECT id, city, park, username_hash, comment, time, rating,
                   sentiment_score, bert_sentiment_score, bert_sentiment_label,
                   qwen_sentiment_score
            FROM posts
            ORDER BY id
        """,
        "create": """
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY,
                city TEXT,
                park TEXT,
                username_hash TEXT,
                comment TEXT,
                time TEXT,
                rating TEXT,
                sentiment_score REAL,
                bert_sentiment_score REAL,
                bert_sentiment_label TEXT,
                qwen_sentiment_score REAL
            )
        """,
        "columns": [
            "id", "city", "park", "username_hash", "comment", "time", "rating",
            "sentiment_score", "bert_sentiment_score", "bert_sentiment_label",
            "qwen_sentiment_score",
        ],
    },
    "images": {
        "select": """
            SELECT id, post_id, username_hash, path, analyzed_bio
            FROM images
            ORDER BY id
        """,
        "create": """
            CREATE TABLE images (
                id INTEGER PRIMARY KEY,
                post_id INTEGER,
                username_hash TEXT,
                path TEXT,
                analyzed_bio INTEGER
            )
        """,
        "columns": ["id", "post_id", "username_hash", "path", "analyzed_bio"],
    },
    "image_species": {
        "select": """
            SELECT id, image_id, species, confidence
            FROM image_species
            ORDER BY id
        """,
        "create": """
            CREATE TABLE image_species (
                id INTEGER PRIMARY KEY,
                image_id INTEGER,
                species TEXT,
                confidence REAL
            )
        """,
        "columns": ["id", "image_id", "species", "confidence"],
    },
    "image_activity": {
        "select": """
            SELECT id, image_id, activity
            FROM image_activity
            ORDER BY id
        """,
        "create": """
            CREATE TABLE image_activity (
                id INTEGER PRIMARY KEY,
                image_id INTEGER,
                activity TEXT
            )
        """,
        "columns": ["id", "image_id", "activity"],
    },
    "post_qwen_detail": {
        "select": """
            SELECT id, post_id, emotions, influence_of_emotions,
                   text_species_mentions, feeling_correlated_to_text_species,
                   text_activities_or_facilities,
                   feeling_correlated_to_text_activities_or_facilities,
                   raw_response, created_at
            FROM post_qwen_detail
            ORDER BY id
        """,
        "create": """
            CREATE TABLE post_qwen_detail (
                id INTEGER PRIMARY KEY,
                post_id INTEGER,
                emotions TEXT,
                influence_of_emotions TEXT,
                text_species_mentions TEXT,
                feeling_correlated_to_text_species TEXT,
                text_activities_or_facilities TEXT,
                feeling_correlated_to_text_activities_or_facilities TEXT,
                raw_response TEXT,
                created_at TEXT
            )
        """,
        "columns": [
            "id", "post_id", "emotions", "influence_of_emotions",
            "text_species_mentions", "feeling_correlated_to_text_species",
            "text_activities_or_facilities",
            "feeling_correlated_to_text_activities_or_facilities",
            "raw_response", "created_at",
        ],
    },
    "image_qwen_detail": {
        "select": """
            SELECT id, image_id, image_summary, visible_species,
                   landscape_elements, human_activities, plants_detected,
                   animals_detected, human_activities_detected,
                   raw_response, created_at
            FROM image_qwen_detail
            ORDER BY id
        """,
        "create": """
            CREATE TABLE image_qwen_detail (
                id INTEGER PRIMARY KEY,
                image_id INTEGER,
                image_summary TEXT,
                visible_species TEXT,
                landscape_elements TEXT,
                human_activities TEXT,
                plants_detected TEXT,
                animals_detected TEXT,
                human_activities_detected TEXT,
                raw_response TEXT,
                created_at TEXT
            )
        """,
        "columns": [
            "id", "image_id", "image_summary", "visible_species",
            "landscape_elements", "human_activities", "plants_detected",
            "animals_detected", "human_activities_detected", "raw_response",
            "created_at",
        ],
    },
    "ingestion_status": {
        "select": """
            SELECT id, filename, status, last_processed_row, created_at, updated_at
            FROM ingestion_status
            ORDER BY id
        """,
        "create": """
            CREATE TABLE ingestion_status (
                id INTEGER PRIMARY KEY,
                filename TEXT,
                status TEXT,
                last_processed_row INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
        """,
        "columns": ["id", "filename", "status", "last_processed_row", "created_at", "updated_at"],
    },
}


def run_copy(project_dir: Path, sql: str) -> list[dict[str, str]]:
    copy_sql = f"COPY ({sql}) TO STDOUT WITH CSV HEADER"
    cmd = [
        "sudo",
        "docker",
        "compose",
        "--project-directory",
        str(project_dir),
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "myuser",
        "-d",
        "mydb",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-P",
        "pager=off",
        "-c",
        copy_sql,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    reader = csv.DictReader(io.StringIO(result.stdout))
    return list(reader)


def normalize_value(value: str | None):
    if value is None or value == "":
        return None
    if value in {"t", "true", "True"}:
        return 1
    if value in {"f", "false", "False"}:
        return 0
    return value


def write_table(conn: sqlite3.Connection, table_name: str, spec: dict[str, object], rows: list[dict[str, str]]) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    conn.execute(spec["create"])
    columns: list[str] = list(spec["columns"])
    placeholders = ", ".join(["?" for _ in columns])
    insert_sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
    values = [tuple(normalize_value(row.get(col)) for col in columns) for row in rows]
    if values:
        conn.executemany(insert_sql, values)


def export_snapshot(project_dir: Path, output_path: Path) -> None:
    subprocess.run(["sudo", "-v"], check=True)

    if output_path.exists():
        raise FileExistsError(f"Output file already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sqlite_conn = sqlite3.connect(output_path)
    try:
        sqlite_conn.execute(
            "CREATE TABLE export_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        sqlite_conn.executemany(
            "INSERT INTO export_meta (key, value) VALUES (?, ?)",
            [
                ("source_project_dir", str(project_dir)),
                ("source_database", "postgres/mydb"),
                ("exported_at_utc", datetime.now(timezone.utc).isoformat()),
            ],
        )

        for table_name, spec in TABLES.items():
            rows = run_copy(project_dir, str(spec["select"]))
            write_table(sqlite_conn, table_name, spec, rows)
            print(f"exported {table_name}: {len(rows)} rows")

        sqlite_conn.commit()
    finally:
        sqlite_conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export current analysis results from Postgres into a new SQLite snapshot database"
    )
    parser.add_argument(
        "--project-dir",
        default=str(Path(__file__).resolve().parents[1]),
        help="Path to the ProjectNew directory containing docker-compose.yml",
    )
    parser.add_argument(
        "--output",
        default="analysis_snapshot.sqlite3",
        help="Output SQLite file path (must not already exist)",
    )
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    if not project_dir.is_dir():
        raise FileNotFoundError(f"Project directory not found: {project_dir}")

    output_path = Path(args.output).resolve()
    try:
        export_snapshot(project_dir, output_path)
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or str(exc), file=sys.stderr)
        raise SystemExit(exc.returncode)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)

    print(f"snapshot written to {output_path}")


if __name__ == "__main__":
    main()