import argparse
from pathlib import Path

import pandas as pd
import torch
import open_clip


def extract_and_tokenize(xlsx_path: Path, names_out: Path, tokens_out: Path, model_name: str):
    df = pd.read_excel(xlsx_path, engine="openpyxl", header=0)
    # take first column (species latin names)
    first_col = df.iloc[:, 0].astype(str).str.strip()
    names = first_col[first_col.notna() & (first_col != "")].drop_duplicates().tolist()

    names_out.parent.mkdir(parents=True, exist_ok=True)
    tokens_out.parent.mkdir(parents=True, exist_ok=True)

    # save plain names (one per line)
    names_out.write_text("\n".join(names), encoding="utf-8")

    # tokenize using open_clip tokenizer for the chosen model
    tokenizer = open_clip.get_tokenizer(model_name)
    token_tensor = tokenizer(names)  # returns torch.LongTensor
    # ensure on cpu and detached
    token_tensor = token_tensor.cpu()

    # save token tensor and names together
    torch.save({"names": names, "tokens": token_tensor}, tokens_out)

if __name__ == "__main__":
    input_xlsx = "植物界-2024-47474.xlsx"
    names_output = "species_names_latin.txt"
    tokens_output = "species_tokens_latin.pt"
    model_identifier = "hf-hub:imageomics/bioclip-2"
    extract_and_tokenize(
        Path(input_xlsx),
        Path(names_output),
        Path(tokens_output),
        model_identifier
    )