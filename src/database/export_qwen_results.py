#!/usr/bin/env python3
"""Export Qwen analysis results from Postgres to Excel (.xlsx) with two sheets:
  1. batch_results  — one row per user batch
  2. image_details  — one row per image
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd
import psycopg2


def export(dsn: str, output: str) -> None:
    conn = psycopg2.connect(dsn)

    # ── Sheet 1: batch-level results ─────────────────────────────────
    batch_sql = """
        SELECT
            id,
            city,
            park,
            username_hash,
            post_ids,
            emotions,
            influence_of_emotions,
            text_species_mentions,
            feeling_correlated_to_text_species,
            text_activities_or_facilities,
            feeling_correlated_to_text_activities_or_facilities,
            comment_sentiment_score,
            association_likelihood,
            association_summary,
            created_at
        FROM qwen_batch_results
        ORDER BY id
    """
    df_batch = pd.read_sql(batch_sql, conn)

    # ── Sheet 2: per-image detail ────────────────────────────────────
    image_sql = """
        SELECT
            d.id,
            d.image_id,
            d.batch_result_id,
            d.image_summary,
            d.visible_species,
            d.landscape_elements,
            d.human_activities,
            i.path AS image_path,
            b.city,
            b.park,
            b.username_hash
        FROM image_qwen_detail d
        JOIN images i ON i.id = d.image_id
        JOIN qwen_batch_results b ON b.id = d.batch_result_id
        ORDER BY d.id
    """
    df_image = pd.read_sql(image_sql, conn)

    conn.close()

    # ── Write to Excel ───────────────────────────────────────────────
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_batch.to_excel(writer, sheet_name="batch_results", index=False)
        df_image.to_excel(writer, sheet_name="image_details", index=False)

    print(f"Exported {len(df_batch)} batch results + {len(df_image)} image details → {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Qwen results to Excel")
    parser.add_argument(
        "--dsn",
        default="dbname=mydb user=myuser password=mypass host=localhost port=5432",
        help="Postgres connection string",
    )
    parser.add_argument(
        "-o", "--output",
        default="qwen_results.xlsx",
        help="Output file path (.xlsx)",
    )
    args = parser.parse_args()
    export(args.dsn, args.output)


if __name__ == "__main__":
    main()
