import argparse
import json
from pathlib import Path
import pandas as pd

def find_column(df: pd.DataFrame, candidates: list[str]) -> str:
    normalized = {str(col).strip().lower(): col for col in df.columns}
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
        lowered = candidate.strip().lower()
        if lowered in normalized:
            return normalized[lowered]
    return None

def main():
    parser = argparse.ArgumentParser(description="Match JSONL results back to original CSVs for human inspection")
    parser.add_argument("--data_dir", required=True, help="Root directory containing the original CSVs")
    parser.add_argument("--results_dir", required=True, help="Directory containing comments_output.jsonl")
    parser.add_argument("--output_csv", default="comments_inspection.csv", help="Output merged CSV path")
    args = parser.parse_args()

    jsonl_file = Path(args.results_dir) / "comments_output.jsonl"
    if not jsonl_file.exists():
        print(f"Error: Cannot find {jsonl_file}")
        return

    print("Loading JSONL into memory...")
    results_map = {}
    with open(jsonl_file, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            try:
                rec = json.loads(line)
                # Composite key matching what we used in generation
                k = (str(rec.get("directory", "")), str(rec.get("csv_filename", "")), str(rec.get("username", "")))
                results_map[k] = rec
            except Exception as e:
                print(f"Skipping malformed JSON line: {e}")

    print(f"Loaded {len(results_map)} records from JSONL.")
    
    csv_paths = list(Path(args.data_dir).rglob("*.csv"))
    print(f"Found {len(csv_paths)} original CSV files. Matching records...")

    merged_rows = []
    
    for cp in csv_paths:
        dir_name = cp.parent.name
        csv_filename = cp.name
        
        try:
            df = pd.read_csv(cp)
            uname_col = find_column(df, ["用户名", "username", "user_name", "原始用户名", "user", "昵称"])
            if not uname_col:
                continue
        except Exception:
            continue
            
        for _, row in df.iterrows():
            uname = str(row[uname_col]).strip() if pd.notna(row[uname_col]) else ""
            key = (dir_name, csv_filename, uname)
            
            rec = results_map.get(key)
            if not rec: 
                continue
                
            out_row = row.to_dict()
            out_row["_qwen_parse_ok"] = rec.get("parse_ok")
            out_row["_qwen_error"] = rec.get("error")
            
            parsed = rec.get("parsed_json", {})
            # Handle both flat and nested 'text_analysis' schemas
            text_analysis = parsed.get("text_analysis", parsed) if isinstance(parsed, dict) else {}
            
            out_row["qwen_emotions"] = str(text_analysis.get("emotions", ""))
            out_row["qwen_influence_of_emotions"] = str(text_analysis.get("influence_of_emotions", ""))
            out_row["qwen_species_mentions"] = str(text_analysis.get("text_species_mentions", ""))
            out_row["qwen_feeling_correlated_to_species"] = str(text_analysis.get("feeling_correlated_to_text_species", ""))
            out_row["qwen_activities_or_facilities"] = str(text_analysis.get("text_activities_or_facilities", ""))
            out_row["qwen_feeling_correlated_to_activities"] = str(text_analysis.get("feeling_correlated_to_text_activities_or_facilities", ""))
            
            # Put raw response at the very end
            out_row["_raw_response"] = rec.get("raw_response", "")
            
            merged_rows.append(out_row)

    if merged_rows:
        out_df = pd.DataFrame(merged_rows)
        # Using utf-8-sig so Excel automatically recognizes Chinese characters properly
        out_df.to_csv(args.output_csv, index=False, encoding='utf-8-sig')
        print(f"Success! Saved {len(merged_rows)} matched records to '{args.output_csv}'.")
    else:
        print("No matched records found. Check if the --data_dir matches the paths originally scanned.")

if __name__ == "__main__":
    main()
