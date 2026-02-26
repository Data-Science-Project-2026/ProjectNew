"""Strip IP-location suffix from the '时间' column in CSV files.

Usage:
    python -m database.clean_csv_time data/csvs/
    python -m database.clean_csv_time data/csvs/some_file.csv

Before: "2024-11-27IP属地：北京"
After:  "2024-11-27"
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
from pathlib import Path

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def clean_time_column(csv_path: Path) -> int:
    """Rewrite the CSV in-place, keeping only the date part in '时间'.

    Returns the number of rows modified.
    """
    tmp = csv_path.with_suffix(".csv.tmp")
    modified = 0

    with csv_path.open("r", encoding="utf-8-sig", newline="") as fin, \
         tmp.open("w", encoding="utf-8", newline="") as fout:
        reader = csv.DictReader(fin)
        if reader.fieldnames is None:
            raise ValueError(f"No header in {csv_path}")
        if "时间" not in reader.fieldnames:
            print(f"  skip {csv_path.name}: no '时间' column")
            tmp.unlink(missing_ok=True)
            return 0

        writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            raw = row.get("时间", "") or ""
            m = _DATE_RE.match(raw.strip())
            if m and m.group(1) != raw.strip():
                row["时间"] = m.group(1)
                modified += 1
            writer.writerow(row)

    # atomic replace
    shutil.move(str(tmp), str(csv_path))
    return modified


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean '时间' column in CSV files (keep date only)")
    parser.add_argument("path", help="CSV file or directory containing CSV files")
    args = parser.parse_args()

    target = Path(args.path)
    if target.is_file():
        files = [target]
    elif target.is_dir():
        files = sorted(target.glob("*.csv"))
    else:
        raise FileNotFoundError(f"{target} not found")

    for f in files:
        n = clean_time_column(f)
        print(f"  {f.name}: {n} rows cleaned")


if __name__ == "__main__":
    main()
