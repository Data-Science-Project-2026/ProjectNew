import argparse
from pathlib import Path

import pandas as pd
import torch
import open_clip


DEFAULT_MODEL_NAME = "ViT-L-14"
DEFAULT_MODEL_CHECKPOINT = Path("open_clip_pytorch_model.bin")


def _write_names_file(names_out: Path, names: list[str], source_path: Path | None = None) -> None:
    # If caller points names output at the same input file, keep the file untouched.
    if source_path is not None:
        try:
            if names_out.resolve() == source_path.resolve():
                print(f"Keeping existing names file unchanged: {names_out}")
                return
        except OSError:
            pass

    payload = "\n".join(names)
    if payload:
        payload += "\n"
    names_out.write_text(payload, encoding="utf-8")
    print(f"Wrote {len(names)} lines to {names_out}")


def extract_and_tokenize(xlsx_path: Path, names_out: Path, tokens_out: Path, model_name: str, include_kingdoms=None, exclude_phyla=None, name_col: str = "Species"):
    df = pd.read_excel(xlsx_path, engine="openpyxl", header=0, dtype=str)

    # build a case-insensitive mapping of column name -> actual column
    col_map = {c.strip().lower(): c for c in df.columns}

    # filter by kingdom if requested
    if include_kingdoms:
        if "kingdom" in col_map:
            df = df[df[col_map["kingdom"]].isin(include_kingdoms)]
        else:
            print("Warning: 'Kingdom' column not found in XLSX — skipping kingdom filter")

    # filter out unwanted phyla if requested
    if exclude_phyla:
        if "phylum" in col_map:
            # normalize and filter case-insensitively
            exset = {p.strip().lower() for p in exclude_phyla if p}
            phcol = df[col_map["phylum"]].astype(str).str.strip().str.lower()
            df = df[~phcol.isin(exset)]
        else:
            print("Warning: 'Phylum' column not found in XLSX — cannot exclude phyla")

    # choose the species name column if present, otherwise try common alternatives, then first column
    requested = name_col.strip().lower() if name_col else None
    if requested and requested in col_map:
        col = df[col_map[requested]]
    elif "species" in col_map:
        col = df[col_map["species"]]
    else:
        col = df.iloc[:, 0]

    first_col = col.astype(str).str.strip()
    names = first_col[first_col.notna() & (first_col != "")].tolist()

    names_out.parent.mkdir(parents=True, exist_ok=True)
    tokens_out.parent.mkdir(parents=True, exist_ok=True)

    # save plain names (one per line)
    _write_names_file(names_out, names)

    # tokenize using open_clip tokenizer for the chosen model
    tokenizer = open_clip.get_tokenizer(model_name)
    token_tensor = tokenizer(names)  # returns torch.LongTensor
    # ensure on cpu and detached
    token_tensor = token_tensor.cpu()

    # save token tensor and names together
    torch.save({"names": names, "tokens": token_tensor}, tokens_out)


def extract_and_tokenize_from_txt(txt_path: Path, names_out: Path, tokens_out: Path, model_name: str, name_col: str = "scientificName"):
    # count lines and print at start
    try:
        with txt_path.open("r", encoding="utf-8") as f:
            line_count = sum(1 for _ in f)
    except Exception:
        # fallback to 0 if can't open
        line_count = 0
    print(f"Lines in {txt_path}: {line_count}")

    raw_lines = txt_path.read_text(encoding="utf-8").splitlines()
    non_empty = [line.strip() for line in raw_lines if line.strip()]
    first_non_empty = non_empty[0] if non_empty else ""
    is_tabular = "\t" in first_non_empty

    if is_tabular:
        # Read tabular TXT/TSV that includes a header row.
        df = pd.read_csv(txt_path, sep="\t", header=0, dtype=str, engine="python")

        # filter by kingdom if present and a filter was provided via global variable
        # note: include_kingdoms will be injected via optional attribute on function (see CLI caller)
        include_kingdoms = getattr(extract_and_tokenize_from_txt, "include_kingdoms", None)
        if include_kingdoms:
            if "kingdom" in df.columns:
                df = df[df["kingdom"].isin(include_kingdoms)]
            else:
                print("Warning: 'kingdom' column not found in TXT — skipping kingdom filter")

        # filter out unwanted phyla if provided via function attribute
        exclude_phyla = getattr(extract_and_tokenize_from_txt, "exclude_phyla", None)
        if exclude_phyla:
            if "phylum" in df.columns:
                exset = {p.strip().lower() for p in exclude_phyla if p}
                phcol = df["phylum"].astype(str).str.strip().str.lower()
                df = df[~phcol.isin(exset)]
            else:
                print("Warning: 'phylum' column not found in TXT — cannot exclude phyla")

        # prefer the named column if present, otherwise fall back to the 4th column (scientificName position)
        if name_col in df.columns:
            col = df[name_col]
        else:
            # protect against files with fewer columns
            if df.shape[1] > 3:
                col = df.iloc[:, 3]
            else:
                col = df.iloc[:, 0]

        first_col = col.astype(str).str.strip()
        names = first_col[first_col.notna() & (first_col != "")].tolist()
    else:
        # For plain one-name-per-line files, keep every non-empty line as-is.
        names = non_empty

    names_out.parent.mkdir(parents=True, exist_ok=True)
    tokens_out.parent.mkdir(parents=True, exist_ok=True)

    _write_names_file(names_out, names, source_path=txt_path)

    tokenizer = open_clip.get_tokenizer(model_name)
    token_tensor = tokenizer(names)
    token_tensor = token_tensor.cpu()

    torch.save({"names": names, "tokens": token_tensor}, tokens_out)


def validate_local_model_weights(model_name: str, checkpoint_path: Path, allow_remote_model: bool) -> None:
    if model_name.startswith("hf-hub:") and not allow_remote_model:
        raise RuntimeError(
            "Remote hf-hub model loading is disabled. "
            "Use --model ViT-L-14 (or another local architecture) with --model-checkpoint."
        )

    if not checkpoint_path.exists():
        raise FileNotFoundError(
            f"Local checkpoint not found: {checkpoint_path}"
        )

    # Validate model/checkpoint compatibility once up-front.
    open_clip.create_model_and_transforms(
        model_name,
        pretrained=str(checkpoint_path),
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tokenize species names from XLSX or TXT and save tokens + names")
    parser.add_argument("input_path", help="Path to input .xlsx or .txt file")
    parser.add_argument(
        "output1",
        help=(
            "For .txt/.tsv input: output .pt path. "
            "For .xlsx/.xls input: output .txt path for names"
        ),
    )
    parser.add_argument(
        "output2",
        nargs="?",
        help="For .xlsx/.xls input only: output .pt path for tokens",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME, help="OpenCLIP model identifier")
    parser.add_argument(
        "--model-checkpoint",
        default=str(DEFAULT_MODEL_CHECKPOINT),
        help="Path to local OpenCLIP checkpoint (used to validate architecture compatibility)",
    )
    parser.add_argument(
        "--allow-remote-model",
        action="store_true",
        help="Allow hf-hub model identifiers. Disabled by default.",
    )
    parser.add_argument("--name-col", default="scientificName", help="Column name to use for species names in TXT file")
    parser.add_argument("--kingdoms", default=None, help="Comma-separated list of kingdoms to include (e.g. Animalia,Plantae,Insecta)")
    args = parser.parse_args()

    inp = Path(args.input_path)
    model_identifier = args.model
    model_checkpoint = Path(args.model_checkpoint)

    validate_local_model_weights(
        model_name=model_identifier,
        checkpoint_path=model_checkpoint,
        allow_remote_model=args.allow_remote_model,
    )

    # parse kingdoms list if provided
    if args.kingdoms:
        kingdoms = [k.strip() for k in args.kingdoms.split(",") if k.strip()]
    else:
        kingdoms = None

    exclude_phyla = None  # could add CLI arg for this if needed

    if inp.suffix.lower() in (".xlsx", ".xls"):
        if args.output2 is None:
            parser.error("Excel input requires 3 positional arguments: input_path names_output tokens_output")
        names_out = Path(args.output1)
        tokens_out = Path(args.output2)
        extract_and_tokenize(inp, names_out, tokens_out, model_identifier, include_kingdoms=kingdoms, exclude_phyla=exclude_phyla, name_col=args.name_col)
    elif inp.suffix.lower() in (".txt", ".tsv"):
        if args.output2 is not None:
            names_out = Path(args.output1)
            tokens_out = Path(args.output2)
        else:
            # Simple TXT/TSV mode: keep input names file unchanged and only write tokens.
            names_out = inp
            tokens_out = Path(args.output1)
        # attach kingdoms to function so it can access the filter
        setattr(extract_and_tokenize_from_txt, "include_kingdoms", kingdoms)
        # attach exclude phyla list to function as well
        setattr(extract_and_tokenize_from_txt, "exclude_phyla", exclude_phyla)
        extract_and_tokenize_from_txt(inp, names_out, tokens_out, model_identifier, name_col=args.name_col)
    else:
        raise ValueError("Unsupported input file type. Provide .xlsx or .txt/.tsv")