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

@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

# configuration
API_KEY = os.environ.get("OPENAI_API_KEY", "EMPTY")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:8000/v1")

DEFAULT_MODEL = os.environ.get("MODEL", "Qwen/Qwen3.5-4B")
DEFAULT_IMAGE_MODEL = os.environ.get("IMAGE_MODEL", DEFAULT_MODEL)
DEFAULT_TEXT_MODEL = os.environ.get("TEXT_MODEL", DEFAULT_MODEL)
DEFAULT_MAX_TOKENS = int(os.environ.get("QWEN_MAX_TOKENS", "512"))
MAX_COMMENT_CHARS = int(os.environ.get("QWEN_MAX_COMMENT_CHARS", "800"))

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

# Stub mode is explicitly controlled by QWEN_STUB_MODE.
# If not set, we keep backward-compatible behavior and enable stubs when
# no API key is provided.
_stub_mode_raw = os.environ.get("QWEN_STUB_MODE")
if _stub_mode_raw is None:
    STUB_MODE = API_KEY in (None, "", "EMPTY")
else:
    STUB_MODE = _stub_mode_raw.strip().lower() in ("1", "true", "yes", "on")

logger.info("Qwen stub mode: %s (QWEN_STUB_MODE=%s, OPENAI_BASE_URL=%s)", STUB_MODE, _stub_mode_raw, BASE_URL)

_low_context_raw = os.environ.get("QWEN_LOW_CONTEXT_MODE")
if _low_context_raw is None:
    LOW_CONTEXT_MODE = DEFAULT_MAX_TOKENS <= 512
else:
    LOW_CONTEXT_MODE = _low_context_raw.strip().lower() in ("1", "true", "yes", "on")

COMPACT_COMMENT_INSTRUCTION = (
    "Return JSON only with key text_analysis. "
    "Inside text_analysis return only these keys: emotions, influence_of_emotions, text_species_mentions, "
    "feeling_correlated_to_text_species, text_activities_or_facilities, "
    "feeling_correlated_to_text_activities_or_facilities, comment_sentiment. "
    "Keep output compact: max 3 items per list, short phrases only, and influence_of_emotions must be one short sentence under 16 words. "
    "English only. Use [] for empty lists. comment_sentiment must be an object with score_0_to_1 only."
)

COMPACT_IMAGE_INSTRUCTION = (
    "Return JSON only with key image_analysis_per_image (array). "
    "For each image include: image_summary, visible_species_in_image, landscape_elements, "
    "human_activities_in_image, plants_detected, animals_detected, human_activities_detected. "
    "Output English only. Use [] for empty lists."
)


def _effective_instruction(instruction: str, compact_instruction: str) -> str:
    if LOW_CONTEXT_MODE:
        return compact_instruction
    return instruction


def _compact_comment_text(comment: str) -> str:
    text = str(comment).strip()
    if LOW_CONTEXT_MODE and len(text) > MAX_COMMENT_CHARS:
        return text[:MAX_COMMENT_CHARS]
    return text


logger.info(
    "Qwen low-context mode: %s (QWEN_LOW_CONTEXT_MODE=%s, DEFAULT_MAX_TOKENS=%s, MAX_COMMENT_CHARS=%s)",
    LOW_CONTEXT_MODE,
    _low_context_raw,
    DEFAULT_MAX_TOKENS,
    MAX_COMMENT_CHARS,
)

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


def _looks_truncated_json(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if cleaned.endswith("}") or cleaned.endswith("]") or cleaned.endswith("```"):
        return False
    return "{" in cleaned or "[" in cleaned

def _run_qwen_inference(messages: list, config: dict):
    model = config.get("model")
    # Keep generation bounded for low-memory local backends with small max_model_len.
    base_max_tokens = min(int(config.get("max_tokens", DEFAULT_MAX_TOKENS)), DEFAULT_MAX_TOKENS)
    temperature = config.get("temperature", 0.7)
    
    max_retries = 3
    parsed = None
    raw_response = ""
    # Local stub mode: return a small, well-formed JSON structure expected
    # by the orchestrator instead of calling out to the API.
    if STUB_MODE:
        # detect whether this is an image or text request by scanning messages
        is_image = False
        for m in messages:
            if isinstance(m.get("content"), list):
                for item in m.get("content"):
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        is_image = True
                        break
            if is_image:
                break

        if is_image:
            # return a simple image analysis envelope similar to model output
            return {
                "image_analysis_per_image": [
                    {
                        "image_summary": "stub: no notable objects",
                        "visible_species_in_image": [],
                        "landscape_elements": [],
                        "human_activities_in_image": [],
                        "plants_detected": [],
                        "animals_detected": [],
                        "human_activities_detected": [],
                    }
                ]
            }
        else:
            # comment/text analysis stub
            return {
                "text_analysis": {
                    "emotions": [],
                    "influence_of_emotions": None,
                    "text_species_mentions": [],
                    "feeling_correlated_to_text_species": [],
                    "text_activities_or_facilities": [],
                    "feeling_correlated_to_text_activities_or_facilities": [],
                    "comment_sentiment": {"score_0_to_1": 0.5},
                }
            }
    for attempt in range(1, max_retries + 1):
        try:
            attempt_max_tokens = min(base_max_tokens + (attempt - 1) * 64, DEFAULT_MAX_TOKENS)
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=attempt_max_tokens,
                temperature=temperature,
                top_p=0.8,
                presence_penalty=1.5,
                response_format={"type": "json_object"},
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
                if attempt < max_retries and _looks_truncated_json(raw_response):
                    logger.warning(
                        "JSON parse failed on attempt %d/%d and output looks truncated; retrying with max_tokens=%d",
                        attempt,
                        max_retries,
                        min(base_max_tokens + attempt * 64, DEFAULT_MAX_TOKENS),
                    )
                    time.sleep(attempt)
                    continue

            break
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
    instruction = _effective_instruction(instruction, COMPACT_IMAGE_INSTRUCTION)
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
                        "text": "Return JSON only. English only. Use [] for empty lists.",
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
@app.route("/analyze_users", methods=["POST"])
def analyze_comments():
    payload = request.get_json(force=True)
    comments = payload.get("comments", []) # List of text comments
    config = payload.get("config", {})
    
    instruction = config.get("instruction") or _COMMENT_INSTRUCTION
    instruction = _effective_instruction(instruction, COMPACT_COMMENT_INSTRUCTION)
    config["model"] = config.get("model") or DEFAULT_TEXT_MODEL
    
    results = []
    
    for comment in comments:
        compact_comment = _compact_comment_text(comment)
        if LOW_CONTEXT_MODE:
            messages = [
                {
                    "role": "user",
                    "content": (
                        "JSON only. English only. Use [] for empty lists. Keep the answer compact. "
                        "Return: text_analysis{emotions,influence_of_emotions,text_species_mentions,"
                        "feeling_correlated_to_text_species,text_activities_or_facilities,"
                        "feeling_correlated_to_text_activities_or_facilities,"
                        "comment_sentiment:{score_0_to_1}}. Max 3 items per list. influence_of_emotions must be one short sentence under 16 words. "
                        f"Comment: {compact_comment}"
                    ),
                }
            ]
        else:
            messages = [
                {"role": "system", "content": instruction},
                {
                    "role": "user",
                    "content": f"Analyze this comment and return JSON only. Comment: {compact_comment}",
                }
            ]
        
        parsed = _run_qwen_inference(messages, config)
        results.append(parsed)
        
    return jsonify({"results": results})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
