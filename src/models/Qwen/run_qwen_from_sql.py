from __future__ import annotations

import argparse
import json

from openai import OpenAI

from .user_sql_reader import build_qwen_messages, build_qwen_user_batches

DEFAULT_INSTRUCTION = """
You are a multimodal ecology + behavior analyst. You will be given:
1) A set of images taken by ONE user at the CURRENT location (a park) during a single visit or short time window.
2) The user's comment text for this user.

Your tasks:
A) Across ALL images, identify distinct PLANT species and ANIMAL species visible.
B) Detect human activities visible in the images.
C) Analyze comment sentiment in [0, 1].
D) Infer image-text association and provide one concise summary.

IMPORTANT CONSTRAINTS:
- Output MUST be valid JSON ONLY.
- Keep JSON compact but complete.
- If uncertain, use lower confidence.

Return JSON schema:
{
  "plants": [{"scientific_name": "...", "common_name": null, "count_estimate": "1|multiple", "confidence": 0.0, "evidence_images": [0]}],
  "animals": [{"scientific_name": "...", "common_name": null, "count_estimate": "1|multiple", "confidence": 0.0, "evidence_images": [0]}],
  "human_activities": [{"activity": "...", "count_estimate": "1|multiple", "confidence": 0.0, "evidence_images": [0]}],
  "comment_sentiment": {"score": 0.0, "brief_justification": "..."},
  "image_text_association": {"association_likelihood": 0.0, "association_summary": "..."}
}
""".strip()


def run() -> None:
    parser = argparse.ArgumentParser(description="Run Qwen VL over user-level SQL batches.")
    parser.add_argument("--db", dest="db_path", default="src/database/data.db", help="Path to SQLite DB")
    parser.add_argument("--base-url", default="http://localhost:8000/v1", help="OpenAI-compatible base URL")
    parser.add_argument("--api-key", default="EMPTY", help="API key")
    parser.add_argument("--model", default="Qwen/Qwen3-VL-8B-Instruct-FP8", help="Model name")
    parser.add_argument("--city", default=None, help="Filter by city")
    parser.add_argument("--park", default=None, help="Filter by park")
    parser.add_argument("--username", default=None, help="Filter by username")
    parser.add_argument("--min-images", type=int, default=1, help="Only keep users with at least N images")
    parser.add_argument("--max-users", type=int, default=1, help="Max number of user batches to run")
    parser.add_argument("--max-tokens", type=int, default=512, help="Max tokens")
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature")
    args = parser.parse_args()

    batches = build_qwen_user_batches(
        args.db_path,
        city=args.city,
        park=args.park,
        username=args.username,
        min_images=args.min_images,
    )

    if not batches:
        print("No eligible user batches found.")
        return

    client = OpenAI(api_key=args.api_key, base_url=args.base_url)

    for index, batch in enumerate(batches[: args.max_users], start=1):
        messages = build_qwen_messages(batch, DEFAULT_INSTRUCTION)
        response = client.chat.completions.create(
            model=args.model,
            messages=messages,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )
        content = response.choices[0].message.content

        print(f"\n=== Batch {index} ===")
        print(f"city={batch.city} park={batch.park} user={batch.username}")
        print(f"posts={len(batch.post_ids)} comments={len(batch.comments)} images={len(batch.images)}")

        try:
            parsed = json.loads(content)
            print(json.dumps(parsed, ensure_ascii=False, indent=2))
        except Exception:
            print(content)


if __name__ == "__main__":
    run()
