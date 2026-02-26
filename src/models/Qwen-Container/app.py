import os
import json
from flask import Flask, request, jsonify
from openai import OpenAI
from models.Qwen.user_sql_reader import build_qwen_messages, QwenUserBatchInput

app = Flask(__name__)

# configuration (OpenAI API key should be provided via env)
API_KEY = os.environ.get("OPENAI_API_KEY")
BASE_URL = os.environ.get("OPENAI_BASE_URL")
MODEL = os.environ.get("MODEL", "qwen-vl-max")
if not API_KEY:
    # service can still start but will reject requests that need OpenAI
    # if no key is provided.  this makes local development easier.
    client = None
else:
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

@app.route("/analyze_users", methods=["POST"])
def analyze_users():
    payload = request.get_json(force=True)
    batch_dicts = payload.get("batches", [])
    # get config from payload
    config = payload.get("config", {})
    instruction = config.get("instruction", "")
    model = config.get("model", MODEL)
    max_tokens = config.get("max_tokens", 512)
    temperature = config.get("temperature", 0.2)

    results = []
    for batch_dict in batch_dicts:
        if client is None:
            results.append({"error": "missing OPENAI_API_KEY"})
            continue
        # reconstruct batch object from dict
        batch = QwenUserBatchInput.from_dict(batch_dict)
        messages = build_qwen_messages(batch, instruction)
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
        results.append(parsed)
    return jsonify({"results": results})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
