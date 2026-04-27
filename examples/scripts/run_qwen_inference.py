import argparse
import json
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from base64 import b64encode
from pathlib import Path

import pandas as pd
from openai import OpenAI

# -----------------------
# Constants and Defaults
# -----------------------
API_KEY = "EMPTY"
MODEL_NAME = "Qwen/Qwen3.6-35B-A3B"
TEMPERATURE = 0.6
TOP_P = 0.95
TOP_K = 20
MAX_TOKENS = 12288
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_CONCURRENT_REQUESTS = 4  # Default concurrent requests

# Thread lock for file writing
file_write_lock = threading.Lock()

# -----------------------
# Helper Functions
# -----------------------
def load_instruction(path: str) -> str:
    return Path(path).read_text(encoding="utf-8").strip()

def image_file_to_data_url(image_path: str) -> str:
    path = Path(image_path)
    mime_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    mime_type = mime_type_map.get(path.suffix.lower(), "application/octet-stream")
    encoded = b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"

def find_column(df: pd.DataFrame, candidates: list[str]) -> str:
    normalized = {str(col).strip().lower(): col for col in df.columns}
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
        lowered = candidate.strip().lower()
        if lowered in normalized:
            return normalized[lowered]
    raise KeyError(f"Failed to find column: {candidates}. Available: {list(df.columns)}")

def message_content_to_text(content) -> str:
    if content is None: return ""
    if isinstance(content, str): return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
            elif item is not None:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)

def keep_content_after_think(raw_text: str) -> str:
    text = raw_text.strip()
    marker = "</think>"
    if marker in text:
        return text.rsplit(marker, 1)[1].strip()
    return text

def extract_json_text(raw_text: str) -> str:
    cleaned = raw_text.strip()
    if not cleaned:
        raise ValueError("Empty model response")
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"): lines = lines[1:]
        if lines and lines[-1].startswith("```"): lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
        if cleaned.lower().startswith("json"): cleaned = cleaned[4:].strip()
    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        pass
    object_start = cleaned.find("{")
    array_start = cleaned.find("[")
    starts = [index for index in (object_start, array_start) if index != -1]
    if not starts:
        raise ValueError("No JSON start token found")
    start = min(starts)
    end = max(cleaned.rfind("}"), cleaned.rfind("]"))
    if end == -1 or end <= start:
        raise ValueError("No JSON end token found")
    candidate = cleaned[start:end + 1]
    json.loads(candidate)
    return candidate

def parse_json_response(raw_text: str) -> dict:
    parsed = json.loads(extract_json_text(raw_text))
    if not isinstance(parsed, dict):
        raise ValueError("Parsed result is not a JSON object")
    return parsed

def repair_json_response(client: OpenAI, instruction_text: str, source_text: str, bad_output: str) -> str:
    repair_user_prompt = (
        "The previous model output failed to provide valid JSON.\n"
        "Convert the content into ONE valid JSON object that strictly follows the required schema.\n"
        "Output JSON only, no explanation, no markdown, no thinking text.\n\n"
        f"Original text:\n{source_text}\n\n"
        f"Previous bad output:\n{bad_output}"
    )
    repair_resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": instruction_text},
            {"role": "user", "content": repair_user_prompt},
        ],
        max_tokens=MAX_TOKENS,
        extra_body={
            "temperature": TEMPERATURE,
            "top_p": TOP_P,
            "top_k": TOP_K,
            "chat_template_kwargs": {"preserve_thinking": True},
            
        },
    )
    repair_text = keep_content_after_think(message_content_to_text(repair_resp.choices[0].message.content))
    return extract_json_text(repair_text)

# -----------------------
# State Management
# -----------------------
def load_processed_keys(jsonl_path: Path, key_fields: list[str]) -> set:
    processed = set()
    if not jsonl_path.exists():
        return processed
    with jsonl_path.open('r', encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            try:
                record = json.loads(line)
                if record.get("parse_ok", False):
                    key = "::".join(str(record.get(k, "")) for k in key_fields)
                    processed.add(key)
            except json.JSONDecodeError:
                continue
    return processed

# -----------------------
# Processing Functions
# -----------------------

def process_single_comment(client: OpenAI, record: dict, comment_text: str, instruction: str) -> dict:
    if not comment_text:
        record.update({"parse_ok": False, "error": "Empty comment, skipped", "raw_response": "", "parsed_json": {}})
        return record

    raw_response = ""
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": instruction},
                {
                    "role": "user",
                    "content": (
                        "Analyze the following comment.\n"
                        "All output text must be in English only.\n"
                        "Never copy Chinese text from the source comment.\n"
                        "For any list with no result, return [] exactly.\n\n"
                        f"Comment:\n{comment_text}"
                    ) 
                },
            ],
            max_tokens=MAX_TOKENS,
            extra_body={
                "temperature": TEMPERATURE,
                "top_p": TOP_P,
                "top_k": TOP_K,
                "chat_template_kwargs": {"preserve_thinking": True}
            },
        )
        raw_response = keep_content_after_think(message_content_to_text(response.choices[0].message.content))
        try:
            parsed = parse_json_response(raw_response)
        except Exception:
            raw_response = repair_json_response(client, instruction, comment_text, raw_response)
            parsed = parse_json_response(raw_response)
            
        record.update({"parse_ok": True, "error": "", "raw_response": raw_response, "parsed_json": parsed})
    except Exception as exc:
        record.update({"parse_ok": False, "error": str(exc), "raw_response": raw_response, "parsed_json": {}})
        
    return record


def process_comments(data_dir: Path, output_file: Path, client: OpenAI, instruction: str, max_concurrent: int):
    print(f"--- Starting Comments Processing ---")
    processed_keys = load_processed_keys(output_file, ["directory", "csv_filename", "username"])
    csv_paths = list(data_dir.rglob("*.csv"))
    print(f"Found {len(csv_paths)} CSV files. Processed state contains {len(processed_keys)} records.")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    tasks = []
    
    with output_file.open('a', encoding='utf-8') as out_f:
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            for csv_path in csv_paths:
                dir_name = csv_path.parent.name
                csv_filename = csv_path.name
                
                try:
                    df = pd.read_csv(csv_path)
                    username_col = find_column(df, ["用户名", "username", "user_name", "原始用户名", "user", "昵称"])
                    comment_col = find_column(df, ["评论", "comment", "comments", "text", "内容"])
                except Exception as e:
                    print(f"Skipping {csv_filename}: {e}")
                    continue

                print(f"Queueing CSV tasks: {csv_filename} ({len(df)} rows)")
                for row_number, (_, row) in enumerate(df.iterrows(), start=1):
                    username = str(row[username_col]).strip() if pd.notna(row[username_col]) else ""
                    comment_text = str(row[comment_col]).strip() if pd.notna(row[comment_col]) else ""
                    
                    state_key = f"{dir_name}::{csv_filename}::{username}"
                    if state_key in processed_keys:
                        continue
                    
                    record = {
                        "directory": dir_name,
                        "csv_filename": csv_filename,
                        "username": username,
                    }
                    
                    tasks.append(executor.submit(process_single_comment, client, record, comment_text, instruction))

            print(f"Successfully queued {len(tasks)} comment tasks. Waiting for completion...")
            for idx, future in enumerate(as_completed(tasks), start=1):
                try:
                    result = future.result()
                    with file_write_lock:
                        out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
                        out_f.flush()
                    if idx % 10 == 0:
                        print(f"Completed {idx}/{len(tasks)} comments.")
                except Exception as exc:
                    print(f"Task generated an exception: {exc}")


def process_single_image(client: OpenAI, record: dict, image_path: Path, instruction: str) -> dict:
    raw_response = ""
    try:
        image_data_url = image_file_to_data_url(str(image_path))
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": instruction},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Analyze this single image as Images[0].\n"
                                "All output text must be in English only.\n"
                                "Never output Chinese text.\n"
                                "For any list or detection module with no result, return [] exactly.\n"
                                "Output only the required JSON."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": image_data_url},
                        },
                    ],
                },
            ],
            max_tokens=MAX_TOKENS,
            extra_body={
                "temperature": TEMPERATURE,
                "top_p": TOP_P,
                "top_k": TOP_K,
                "chat_template_kwargs": {"preserve_thinking": True},
            },
        )
        raw_response = keep_content_after_think(message_content_to_text(response.choices[0].message.content))
        parsed = parse_json_response(raw_response)
        record.update({"parse_ok": True, "error": "", "raw_response": raw_response, "parsed_json": parsed})
    except Exception as exc:
        record.update({"parse_ok": False, "error": str(exc), "raw_response": raw_response, "parsed_json": {}})
        
    return record


def process_images(data_dir: Path, output_file: Path, client: OpenAI, instruction: str, max_concurrent: int):
    print(f"--- Starting Images Processing ---")
    processed_keys = load_processed_keys(output_file, ["directory", "image_filename"])
    
    image_paths = sorted(
        path for path in data_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    print(f"Found {len(image_paths)} Images. Processed state contains {len(processed_keys)} records.")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    tasks = []
    
    with output_file.open('a', encoding='utf-8') as out_f:
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            for idx, image_path in enumerate(image_paths, start=1):
                dir_name = image_path.parent.name
                image_filename = image_path.name
                state_key = f"{dir_name}::{image_filename}"
                
                if state_key in processed_keys:
                    continue
                    
                record = {
                    "directory": dir_name,
                    "image_filename": image_filename,
                }
                
                tasks.append(executor.submit(process_single_image, client, record, image_path, instruction))

            print(f"Successfully queued {len(tasks)} image tasks. Waiting for completion...")
            for idx, future in enumerate(as_completed(tasks), start=1):
                try:
                    result = future.result()
                    with file_write_lock:
                        out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
                        out_f.flush()
                    print(f"[{idx}/{len(tasks)}] Processed Image: {result['image_filename']}")
                except Exception as exc:
                    print(f"Task generated an exception: {exc}")

# -----------------------
# Main Entry Point
# -----------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Standalone Qwen Inference orchestrator for images and comments.")
    parser.add_argument("--data_dir", type=str, required=True, help="Path to the root data directory to traverse.")
    parser.add_argument("--output_dir", type=str, default="./results", help="Directory to store output JSONL files.")
    parser.add_argument("--comment_prompt", type=str, default="comment.md", help="Path to the comment system prompt.")
    parser.add_argument("--image_prompt", type=str, default="images.md", help="Path to the image system prompt.")
    parser.add_argument("--mode", type=str, choices=["all", "comments", "images"], default="all", help="Which processing to run.")
    parser.add_argument("--workers", type=int, default=MAX_CONCURRENT_REQUESTS, help="Maximum concurrent API requests.")
    parser.add_argument("--port", type=int, default=23456, help="Port number for the vLLM API server.")
    
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_url = f"http://localhost:{args.port}/v1"
    client = OpenAI(api_key=API_KEY, base_url=base_url)

    if args.mode in ["all", "comments"]:
        print("\n=== Initializing Comment Inference ===")
        comment_instruction = load_instruction(args.comment_prompt)
        comments_output = output_dir / "comments_output.jsonl"
        process_comments(data_dir, comments_output, client, comment_instruction, args.workers)

    if args.mode in ["all", "images"]:
        print("\n=== Initializing Image Inference ===")
        image_instruction = load_instruction(args.image_prompt)
        images_output = output_dir / "images_output.jsonl"
        process_images(data_dir, images_output, client, image_instruction, args.workers)

    print("\n=== Execution Completed ===")
