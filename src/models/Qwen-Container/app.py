import os
import json
from flask import Flask, request, jsonify
from openai import OpenAI
from models.Qwen.user_sql_reader import build_qwen_messages

app = Flask(__name__)

# configuration (OpenAI API key should be provided via env)
API_KEY = os.environ.get("OPENAI_API_KEY")
BASE_URL = os.environ.get("OPENAI_BASE_URL")
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

@app.route("/analyze_users", methods=["POST"])
def analyze_users():
    payload = request.get_json(force=True)
    batches = payload.get("batches", [])
    results = []
    for batch in batches:
        messages = build_qwen_messages(batch, batch.get("instruction", ""))
        resp = client.chat.completions.create(
            model=batch.get("model"),
            messages=messages,
            max_tokens=batch.get("max_tokens", 512),
            temperature=batch.get("temperature", 0.2),
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
