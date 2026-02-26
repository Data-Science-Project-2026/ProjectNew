import os
import json
import time
import logging
from pathlib import Path
from flask import Flask, request, jsonify
from openai import OpenAI
from models.Qwen.user_sql_reader import build_qwen_messages, QwenUserBatchInput

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# configuration (OpenAI API key should be provided via env)
API_KEY = os.environ.get("OPENAI_API_KEY")
BASE_URL = os.environ.get("OPENAI_BASE_URL")
MODEL = os.environ.get("MODEL", "qwen-vl-max")

# Load default instruction from file if provided via env
_DEFAULT_INSTRUCTION = ""
_INSTRUCTION_FILE = os.environ.get("QWEN_INSTRUCTION_FILE")
if _INSTRUCTION_FILE:
    p = Path(_INSTRUCTION_FILE)
    if p.is_file():
        _DEFAULT_INSTRUCTION = p.read_text(encoding="utf-8").strip()
        print(f"Loaded default instruction from {p} ({len(_DEFAULT_INSTRUCTION)} chars)")

if not API_KEY:
    client = None
else:
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

@app.route("/analyze_users", methods=["POST"])
def analyze_users():
    payload = request.get_json(force=True)
    batch_dicts = payload.get("batches", [])
    # get config from payload
    config = payload.get("config", {})
    instruction = config.get("instruction") or _DEFAULT_INSTRUCTION
    model = config.get("model", MODEL)
    max_tokens = config.get("max_tokens", 512)
    temperature = config.get("temperature", 0.2)

    results = []
    for idx, batch_dict in enumerate(batch_dicts):
        if client is None:
            results.append({"error": "missing OPENAI_API_KEY"})
            continue
        # reconstruct batch object from dict
        batch = QwenUserBatchInput.from_dict(batch_dict)
        messages = build_qwen_messages(batch, instruction)

        # retry with backoff for transient vLLM errors (e.g. mm_cache)
        max_retries = 3
        parsed = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                try:
                    parsed = json.loads(resp.choices[0].message.content)
                except Exception:
                    parsed = {"error": "non-json response", "raw": resp.choices[0].message.content}
                break  # success
            except Exception as exc:
                logger.warning("batch %d attempt %d/%d failed: %s", idx, attempt, max_retries, exc)
                if attempt < max_retries:
                    time.sleep(2 * attempt)  # backoff: 2s, 4s
                else:
                    parsed = {"error": str(exc)}
        results.append(parsed)
    return jsonify({"results": results})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
