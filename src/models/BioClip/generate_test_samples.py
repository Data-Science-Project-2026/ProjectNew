import argparse
from pathlib import Path

import pandas as pd


def choose_samples(xlsx_path: Path, out_path: Path, per_kingdom: int = 40, name_col: str = None, seed: int = 42):
    df = pd.read_excel(xlsx_path, engine="openpyxl", header=0, dtype=str)

    # case-insensitive column map
    col_map = {c.strip().lower(): c for c in df.columns}

    # determine species/name column
    candidates = []
    if name_col:
        candidates.append(name_col.strip().lower())
    candidates += ["species", "scientificname", "scientific_name", "name"]
    species_col = None
    for c in candidates:
        if c in col_map:
            species_col = col_map[c]
            break
    if species_col is None:
        species_col = df.columns[0]

    # determine kingdom column (case-insensitive)
    kingdom_col = col_map.get("kingdom", None)

    targets = [("Plantae", "Plantae"), ("Animalia", "Animalia"), ("Fungi", "Fungi")]
    samples = []

    for label, target in targets:
        if kingdom_col is None:
            # if no kingdom column, try to infer from species names (not implemented) -> skip
            available = df[species_col].astype(str).str.strip().drop_duplicates()
            msg = f"No kingdom column; selecting up to {per_kingdom} from whole file for {label}"
            print(msg)
            picked = available.dropna().loc[available != ""].sample(n=min(len(available), per_kingdom), random_state=seed) if len(available) > 0 else []
        else:
            kcol = df[kingdom_col].astype(str).str.strip().str.lower()
            mask = kcol == target.lower()
            group = df.loc[mask, species_col].astype(str).str.strip().drop_duplicates()
            available = group.loc[group.notna() & (group != "")]
            if len(available) == 0:
                print(f"Warning: no entries found for kingdom '{target}'")
                picked = []
            else:
                picked = available.sample(n=min(len(available), per_kingdom), random_state=seed)
        samples.append((label, list(picked)))

    # write out with simple headers
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for label, items in samples:
        lines.append(f"## {label}")
        lines.extend(items)
        lines.append("")  # blank line between groups

    out_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    for label, items in samples:
        print(f"Wrote {len(items)} samples for {label} to {out_path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Sample species by kingdom from an Excel file")
    p.add_argument("input_xlsx", help="Path to input Excel file (.xlsx/.xls)")
    p.add_argument("output_txt", nargs="?", default="species_samples.txt", help="Output text file (default: species_samples.txt)")
    p.add_argument("--per-kingdom", type=int, default=40, help="Number of samples per kingdom (default: 40)")
    p.add_argument("--name-col", default=None, help="Column name to use for species (optional)")
    p.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    args = p.parse_args()

    choose_samples(Path(args.input_xlsx), Path(args.output_txt), per_kingdom=args.per_kingdom, name_col=args.name_col, seed=args.seed)