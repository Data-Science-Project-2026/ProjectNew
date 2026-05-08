import argparse
import time
from pathlib import Path
from base64 import b64encode

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
TEST_MAX_TOKENS = 12288  # 设置一个较高的上限以便观察实际消耗
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

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
    raise KeyError(f"Failed to find column: {candidates}")

def get_sample_comments(data_dir: Path, n=10) -> list[str]:
    comments = []
    for csv_path in data_dir.rglob("*.csv"):
        try:
            df = pd.read_csv(csv_path)
            comment_col = find_column(df, ["评论", "comment", "comments", "text", "内容"])
            for _, row in df.iterrows():
                text = str(row[comment_col]).strip() if pd.notna(row[comment_col]) else ""
                if text:
                    comments.append(text)
                    if len(comments) >= n:
                        return comments
        except Exception:
            continue
    return comments

def get_sample_images(data_dir: Path, n=10) -> list[Path]:
    image_paths = []
    for path in data_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            image_paths.append(path)
            if len(image_paths) >= n:
                return image_paths
    return image_paths

def main():
    parser = argparse.ArgumentParser(description="Test token usage for 10 comments and 10 images.")
    parser.add_argument("--data_dir", type=str, required=True, help="Path to data directory")
    parser.add_argument("--port", type=int, default=23456, help="vLLM API port")
    parser.add_argument("--comment_prompt", type=str, default="comment.md", help="Comment system prompt")
    parser.add_argument("--image_prompt", type=str, default="images.md", help="Image system prompt")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    client = OpenAI(api_key=API_KEY, base_url=f"http://localhost:{args.port}/v1")

    # Load prompts
    try:
        comment_instruction = load_instruction(args.comment_prompt)
        image_instruction = load_instruction(args.image_prompt)
    except FileNotFoundError as e:
        print(f"Error loading instructions: {e}")
        return

    print(f"Sampling up to 10 comments and 10 images from {data_dir}...")
    sample_comments = get_sample_comments(data_dir, 10)
    sample_images = get_sample_images(data_dir, 10)

    print(f"Found {len(sample_comments)} comments and {len(sample_images)} images to test.\n")

    max_comment_tokens = 0
    max_image_tokens = 0

    print("=== Testing Comments Token Usage ===")
    for i, comment_text in enumerate(sample_comments, 1):
        t0 = time.time()
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": comment_instruction},
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
                max_tokens=TEST_MAX_TOKENS,
                extra_body={
                    "temperature": TEMPERATURE, "top_p": TOP_P, "top_k": TOP_K,
                    "chat_template_kwargs": {"preserve_thinking": True}
                },
            )
            completion_tokens = response.usage.completion_tokens
            prompt_tokens = response.usage.prompt_tokens
            max_comment_tokens = max(max_comment_tokens, completion_tokens)
            print(f"Comment {i:2d} | Prompt: {prompt_tokens:4d} | Completion: {completion_tokens:4d} tokens | Time: {time.time()-t0:.2f}s")
        except Exception as e:
            print(f"Comment {i:2d} | Failed: {e}")

    print("\n=== Testing Images Token Usage ===")
    for i, image_path in enumerate(sample_images, 1):
        t0 = time.time()
        try:
            image_data_url = image_file_to_data_url(str(image_path))
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": image_instruction},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Analyze this single image as Images[0].\nAll output text must be in English only.\nNever output Chinese text.\nFor any list or detection module with no result, return [] exactly.\nOutput only the required JSON."},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                max_tokens=TEST_MAX_TOKENS,
                extra_body={
                    "temperature": TEMPERATURE, "top_p": TOP_P, "top_k": TOP_K,
                    "chat_template_kwargs": {"preserve_thinking": True}
                },
            )
            completion_tokens = response.usage.completion_tokens
            prompt_tokens = response.usage.prompt_tokens
            max_image_tokens = max(max_image_tokens, completion_tokens)
            print(f"Image {i:2d} | Prompt: {prompt_tokens:4d} | Completion: {completion_tokens:4d} tokens | Time: {time.time()-t0:.2f}s")
        except Exception as e:
            print(f"Image {i:2d} | Failed: {e}")

    print("\n" + "="*40)
    print("📋 SUMMARY OF TOKEN USAGE")
    print("="*40)
    print(f"Max Completion Tokens for Comments: {max_comment_tokens}")
    print(f"Max Completion Tokens for Images:   {max_image_tokens}")
    print("\n建议将 MAX_TOKENS 设置为比上述最大值略高 10%~20% 的数值。")
    print("="*40)

if __name__ == "__main__":
    main()
