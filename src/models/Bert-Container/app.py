import os
import json
from flask import Flask, request, jsonify
from models.Bert.llm_analyzer import PsychologicalStateAnalyzer

app = Flask(__name__)

@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

# allow model name to be configured via environment
MODEL_NAME = os.environ.get("SENTIMENT_MODEL", "nlptown/bert-base-multilingual-uncased-sentiment")
analyzer = PsychologicalStateAnalyzer(sentiment_model=MODEL_NAME)

@app.route("/analyze_posts", methods=["POST"])
def analyze_posts():
    payload = request.get_json(force=True)
    comments = payload.get("comments", [])
    scores = analyzer.batch_analyze(comments)
    return jsonify({"scores": scores})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
