import os
import json
import time
import logging
from pathlib import Path
from flask import Flask, request, jsonify
from openai import OpenAI

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# configuration
API_KEY = os.environ.get("OPENAI_API_KEY", "EMPTY")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:8000/v1")

DEFAULT_IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "Qwen/Qwen3.5-4B")
DEFAULT_TEXT_MODEL = os.environ.get("TEXT_MODEL", "Qwen/Qwen3.5-4B")

_IMAGE_INSTRUCTION = ""
_COMMENT_INSTRUCTION = ""

# Load instructions at startup
for var_name, md_file, target_var in [
    ("QWEN_IMAGE_INSTRUCTION", "images.md", "_IMAGE_INSTRUCTION"),
    ("QWEN_COMMENT_INSTRUCTION", "comment.md", "_COMMENT_INSTRUCTION"),
]:
    p = Path(os.environ.get(var_name, Path(__file__).parent / md_file))
    if p.is_file():
        text = p.read_text(encoding="utf-8").strip()
        globals()[target_var] = text
        logger.info(f"Loaded {target_var} from {p} ({len(text)} chars)")
    else:
        logger.warning(f"Could not load instruction file {p}")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

def extract_json_text(raw_text: str) -> str:
    cleaned = raw_text.strip()
    if not cleaned:
        raise ValueError("Model returned empty string")

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
        
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()

    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        pass

    object_start = cleaned.find("{")
    array_start = cleaned.find("[")
    starts = [index for index in (object_start, array_start) if index != -1]
    if not starts:
        raise ValueError("No JSON start character found in response")
    start = min(starts)
    end = max(cleaned.rfind("}"), cleaned.rfind("]"))
    if end == -1 or end <= start:
        raise ValueError("No JSON end character found in response")
    
    candidate = cleaned[start:end + 1]
    # Check if this sub-string is valid
    json.loads(candidate)
    return candidate

def _run_qwen_inference(messages: list, config: dict):
    model = config.get("model")
    max_tokens = config.get("max_tokens", 4096)
    temperature = config.get("temperature", 0.7)
    
    max_retries = 3
    parsed = None
    raw_response = ""
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=0.8,
                presence_penalty=1.5,
                extra_body={
                    "top_k": 20,
                    "chat_template_kwargs": {"enable_thinking": False},
                }
            )
            raw_response = resp.choices[0].message.content
            # Extract content as text handling possibly nested message types
            if isinstance(raw_response, list):
                parts = []
                for item in raw_response:
                    if isinstance(item, dict) and "text" in item:
                        parts.append(str(item["text"]))
                    elif isinstance(item, str):
                        parts.append(item)
                raw_response = "\n".join(parts)
            elif raw_response is None:
                raw_response = ""
            
            try:
                json_str = extract_json_text(raw_response)
                parsed = json.loads(json_str)
                # Successful parse
                return parsed
            except Exception as e:
                parsed = {"error": f"JSON parse error: {e}", "raw": raw_response}
            
            break  # Break out of retry loop if it executed without API error but had JSON error
        except Exception as exc:
            logger.warning("inference attempt %d/%d failed: %s", attempt, max_retries, exc)
            if attempt < max_retries:
                time.sleep(2 * attempt)
            else:
                parsed = {"error": str(exc), "raw": raw_response}
                
    return parsed

@app.route("/analyze_images", methods=["POST"])
def analyze_images():
    payload = request.get_json(force=True)
    images_base64 = payload.get("images", []) # List of base64 strings or URLs
    config = payload.get("config", {})
    
    instruction = config.get("instruction") or _IMAGE_INSTRUCTION
    config["model"] = config.get("model") or DEFAULT_IMAGE_MODEL
    
    results = []
    
    for b64 in images_base64:
        # Standardize the image_url to be used in OpenAI structure
        if not b64.startswith("data:"):
            b64 = f"data:image/jpeg;base64,{b64}"
            
        messages = [
            {"role": "system", "content": instruction},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "All output text must be in English only.\n"
                            "Never output Chinese text.\n"
                            "For any list or detection module with no result, return [] exactly.\n"
                            "Output only the required JSON."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": b64},
                    },
                ]
            }
        ]
        
        parsed = _run_qwen_inference(messages, config)
        results.append(parsed)
        
    return jsonify({"results": results})

@app.route("/analyze_comments", methods=["POST"])
def analyze_comments():
    payload = request.get_json(force=True)
    comments = payload.get("comments", []) # List of text comments
    config = payload.get("config", {})
    
    instruction = config.get("instruction") or _COMMENT_INSTRUCTION
    config["model"] = config.get("model") or DEFAULT_TEXT_MODEL
    
    results = []
    
    for comment in comments:
        messages = [
            {"role": "system", "content": instruction},
            {
                "role": "user",
                "content": (
                    "Analyze the following comment.\n"
                    "All output text must be in English only.\n"
                    "Never copy Chinese text from the source comment.\n"
                    "For any list with no result, return [] exactly.\n\n"
                    f"Comment:\n{comment}"
                )
            }
        ]
        
        parsed = _run_qwen_inference(messages, config)
        results.append(parsed)
        
    return jsonify({"results": results})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
