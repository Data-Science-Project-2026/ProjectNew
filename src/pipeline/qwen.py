from __future__ import annotations

import base64
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from openai import OpenAI
from database import postgres as db

logger = logging.getLogger(__name__)

# -----------------------
# Constants and Defaults
# -----------------------
API_KEY = "EMPTY"
MODEL_NAME = "Qwen/Qwen3.6-35B-A3B"
TEMPERATURE = 0.6
TOP_P = 0.95
TOP_K = 20
MAX_TOKENS = 12288

# -----------------------
# Helper Functions
# -----------------------

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

def repair_json_response(client: OpenAI, model_name: str, instruction_text: str, source_text: str, bad_output: str) -> str:
    repair_user_prompt = (
        "The previous model output failed to provide valid JSON.\n"
        "Convert the content into ONE valid JSON object that strictly follows the required schema.\n"
        "Output JSON only, no explanation, no markdown, no thinking text.\n\n"
        f"Original text:\n{source_text}\n\n"
        f"Previous bad output:\n{bad_output}"
    )
    repair_resp = client.chat.completions.create(
        model=model_name,
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

def _log_progress_milestone(current: int, total: int, *, label: str, step: int = 10) -> None:
    if current <= 0:
        return
    if current % step == 0 or current == total:
        logger.info("%s progress: %d/%d ready", label, current, total)


# -----------------------
# Implementations
# -----------------------

def run_qwen_image_analysis_impl(self, max_images: Optional[int] = None) -> int:
    instruction = ""
    if self.qwen_image_instruction_file:
        p = Path(self.qwen_image_instruction_file)
        if p.is_file():
            instruction = p.read_text(encoding="utf-8").strip()
            logger.info("loaded qwen image instruction from %s (%d chars)", p, len(instruction))

    model_name = self.qwen_image_model if self.qwen_image_model and "3.5-4B" not in self.qwen_image_model else MODEL_NAME
    use_json = bool(self.output_json)
    
    if not self.qwen_service_url:
        logger.warning("No qwen_service_url provided for run_qwen_image_analysis")
        return 0

    client = OpenAI(api_key=API_KEY, base_url=self.qwen_service_url)

    if use_json:
        limit = max_images if max_images else 1000000
        all_images = list(self._json_store.get("images", []))
        existing = {d.get("image_id") for d in self._json_store.get("image_qwen_detail", [])}
        rows = [(img["id"], img.get("path")) for img in all_images if img["id"] not in existing][:limit]
    else:
        with db.connect(self.dsn) as conn:
            db.ensure_schema(conn)
            limit = max_images if max_images else 1000000
            rows = db.claim_images_for_qwen(conn, limit=limit, timeout_seconds=3600)

    if not rows:
        logger.info("no unanalyzed images found for Qwen")
        return 0

    success = 0
    handled_ids: set[int] = set()
    total_rows = len(rows)

    store_lock = threading.Lock()
    workers = int(self.qwen_args.get("workers", MAX_CONCURRENT_REQUESTS))
    
    def process_single_image_row(img_id, img_path):
        if not img_path:
            return img_id, False, "image path is missing", None
        
        p = Path(img_path)
        if not p.is_file():
            return img_id, False, f"image file not found: {img_path}", None
            
        try:
            mime_type_map = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
            }
            mime_type = mime_type_map.get(p.suffix.lower(), "application/octet-stream")
            with open(p, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")
            image_data_url = f"data:{mime_type};base64,{encoded}"

            response = client.chat.completions.create(
                model=model_name,
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
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
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
                raw_response = repair_json_response(client, model_name, instruction, "N/A Image", raw_response)
                parsed = parse_json_response(raw_response)

            nested = parsed.get("image_analysis_per_image")
            if isinstance(nested, list) and nested:
                first = nested[0]
                if isinstance(first, dict):
                    parsed_normalized = first
                else:
                    parsed_normalized = parsed
            else:
                parsed_normalized = parsed

            return img_id, True, "", {"raw": raw_response, "parsed": parsed_normalized}

        except Exception as exc:
            return img_id, False, str(exc), None

    logger.info(f"Starting Qwen image processing with {workers} workers")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_single_image_row, r[0], r[1]): r[0] for r in rows}
        for future in as_completed(futures):
            img_id = futures[future]
            handled_ids.add(int(img_id))
            try:
                out_id, is_ok, error_msg, data = future.result()
                if not is_ok:
                    logger.error("qwen image %d failed: %s", out_id, error_msg)
                    if not use_json:
                        with db.connect(self.dsn) as conn:
                            db.mark_image_qwen_failed(conn, image_id=out_id, error=error_msg)
                else:
                    parsed = data["parsed"]
                    raw_response = data["raw"]
                    vis_species = parsed.get("visible_species_in_image")
                    landscape = parsed.get("landscape_elements")
                    human_acts = parsed.get("human_activities_in_image")
                    plants_detected = parsed.get("plants_detected")
                    animals_detected = parsed.get("animals_detected")
                    human_acts_detected = parsed.get("human_activities_detected")

                    if use_json:
                        with store_lock:
                            self._json_store.setdefault("image_qwen_detail", []).append({
                                "image_id": out_id,
                                "image_summary": parsed.get("image_summary"),
                                "visible_species": vis_species if isinstance(vis_species, list) else None,
                                "landscape_elements": landscape if isinstance(landscape, list) else None,
                                "human_activities": human_acts if isinstance(human_acts, list) else None,
                                "plants_detected": plants_detected if isinstance(plants_detected, list) else None,
                                "animals_detected": animals_detected if isinstance(animals_detected, list) else None,
                                "human_activities_detected": human_acts_detected if isinstance(human_acts_detected, list) else None,
                                "raw_response": raw_response,
                            })
                    else:
                        with db.connect(self.dsn) as conn:
                            db.insert_image_qwen_detail(
                                conn,
                                image_id=out_id,
                                image_summary=parsed.get("image_summary"),
                                visible_species=vis_species if isinstance(vis_species, list) else None,
                                landscape_elements=landscape if isinstance(landscape, list) else None,
                                human_activities=human_acts if isinstance(human_acts, list) else None,
                                plants_detected=plants_detected if isinstance(plants_detected, list) else None,
                                animals_detected=animals_detected if isinstance(animals_detected, list) else None,
                                human_activities_detected=human_acts_detected if isinstance(human_acts_detected, list) else None,
                                raw_response=raw_response,
                            )
                            db.mark_image_qwen_ready(conn, image_id=out_id)
                    
                    success += 1
                    _log_progress_milestone(success, total_rows, label="Qwen images", step=10)

            except Exception as exc:
                logger.error("Future execution failed for image %d: %s", img_id, exc)
                if not use_json:
                    with db.connect(self.dsn) as conn:
                        db.mark_image_qwen_failed(conn, image_id=img_id, error=str(exc))

    if not use_json:
        for img_id, _ in rows:
            if int(img_id) in handled_ids:
                continue
            with db.connect(self.dsn) as conn:
                db.mark_image_qwen_failed(conn, image_id=img_id, error="Qwen image result missing or incomplete")

    logger.info("qwen image service: %d/%d images succeeded", success, len(rows))
    return success


def run_qwen_comment_analysis_impl(self, max_posts: Optional[int] = None) -> int:
    instruction = ""
    if self.qwen_comment_instruction_file:
        p = Path(self.qwen_comment_instruction_file)
        if p.is_file():
            instruction = p.read_text(encoding="utf-8").strip()
            logger.info("loaded qwen comment instruction from %s (%d chars)", p, len(instruction))

    model_name = self.qwen_text_model if self.qwen_text_model and "3.5-4B" not in self.qwen_text_model else MODEL_NAME
    use_json = bool(self.output_json)

    if not self.qwen_service_url:
        logger.warning("No qwen_service_url provided for run_qwen_comment_analysis")
        return 0

    client = OpenAI(api_key=API_KEY, base_url=self.qwen_service_url)

    if use_json:
        limit = max_posts if max_posts else 1000000
        posts = list(self._json_store.get("posts", []))
        existing = {d.get("post_id") for d in self._json_store.get("post_qwen_detail", [])}
        rows = [(p["id"], p.get("comment")) for p in posts if p["id"] not in existing and p.get("comment")][:limit]
        existing_sentiment = {d.get("post_id") for d in self._json_store.get("post_sentiment", [])}
    else:
        with db.connect(self.dsn) as conn:
            db.ensure_schema(conn)
            limit = max_posts if max_posts else 1000000
            rows = db.claim_posts_for_qwen(conn, limit=limit, timeout_seconds=3600)

    if not rows:
        logger.info("no unanalyzed posts found for Qwen")
        return 0

    success = 0
    handled_ids: set[int] = set()
    total_rows = len(rows)

    store_lock = threading.Lock()
    workers = int(self.qwen_args.get("workers", MAX_CONCURRENT_REQUESTS))

    def process_single_comment_row(post_id, comment):
        comment_text = (comment or "").strip()
        try:
            response = client.chat.completions.create(
                model=model_name,
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
                        ),
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
                raw_response = repair_json_response(client, model_name, instruction, comment_text, raw_response)
                parsed = parse_json_response(raw_response)

            text_analysis = parsed.get("text_analysis") if isinstance(parsed, dict) else None
            if not isinstance(text_analysis, dict):
                text_analysis = parsed if isinstance(parsed, dict) else {}

            return post_id, True, "", {"raw": raw_response, "parsed": parsed, "text_analysis": text_analysis}
        except Exception as exc:
            return post_id, False, str(exc), None

    logger.info(f"Starting Qwen comment processing with {workers} workers")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_single_comment_row, r[0], r[1]): r[0] for r in rows}
        for future in as_completed(futures):
            post_id = futures[future]
            handled_ids.add(int(post_id))
            try:
                out_id, is_ok, error_msg, data = future.result()
                if not is_ok:
                    logger.error("qwen post %d failed: %s", out_id, error_msg)
                    if not use_json:
                        with db.connect(self.dsn) as conn:
                            db.mark_post_qwen_failed(conn, post_id=out_id, error=error_msg)
                else:
                    text_analysis = data["text_analysis"]
                    raw_response = data["raw"]

                    emotions = text_analysis.get("emotions")
                    influence = text_analysis.get("influence_of_emotions")
                    ts = text_analysis.get("text_species_mentions")
                    fs = text_analysis.get("feeling_correlated_to_text_species")
                    ta = text_analysis.get("text_activities_or_facilities")
                    fa = text_analysis.get("feeling_correlated_to_text_activities_or_facilities")

                    if use_json:
                        with store_lock:
                            self._json_store.setdefault("post_qwen_detail", []).append({
                                "post_id": out_id,
                                "emotions": emotions if isinstance(emotions, list) else None,
                                "influence_of_emotions": str(influence) if influence else None,
                                "text_species_mentions": ts if isinstance(ts, list) else None,
                                "feeling_correlated_to_text_species": fs if isinstance(fs, list) else None,
                                "text_activities_or_facilities": ta if isinstance(ta, list) else None,
                                "feeling_correlated_to_text_activities_or_facilities": fa if isinstance(fa, list) else None,
                                "raw_response": raw_response,
                            })
                            sentiment = text_analysis.get("comment_sentiment", {})
                            sentiment_score = sentiment.get("score_0_to_1") if isinstance(sentiment, dict) else None
                            if sentiment_score is not None and out_id not in existing_sentiment:
                                self._json_store.setdefault("post_sentiment", []).append({"post_id": out_id, "score": float(sentiment_score)})
                    else:
                        with db.connect(self.dsn) as conn:
                            db.insert_post_qwen_detail(
                                conn,
                                post_id=out_id,
                                emotions=emotions if isinstance(emotions, list) else None,
                                influence_of_emotions=str(influence) if influence else None,
                                text_species_mentions=ts if isinstance(ts, list) else None,
                                feeling_correlated_to_text_species=fs if isinstance(fs, list) else None,
                                text_activities_or_facilities=ta if isinstance(ta, list) else None,
                                feeling_correlated_to_text_activities_or_facilities=fa if isinstance(fa, list) else None,
                                raw_response=raw_response,
                            )
                            sentiment = text_analysis.get("comment_sentiment", {})
                            sentiment_score = sentiment.get("score_0_to_1") if isinstance(sentiment, dict) else None
                            if sentiment_score is not None:
                                db.update_qwen_sentiment(conn, post_id=out_id, score=float(sentiment_score))
                            else:
                                db.mark_post_qwen_ready(conn, post_id=out_id)

                    success += 1
                    _log_progress_milestone(success, total_rows, label="Qwen comments", step=10)

            except Exception as exc:
                logger.error("Future execution failed for post %d: %s", post_id, exc)
                if not use_json:
                    with db.connect(self.dsn) as conn:
                        db.mark_post_qwen_failed(conn, post_id=post_id, error=str(exc))

    if not use_json:
        for post_id, _ in rows:
            if int(post_id) in handled_ids:
                continue
            with db.connect(self.dsn) as conn:
                db.mark_post_qwen_failed(conn, post_id=post_id, error="Qwen post result missing or incomplete")

    logger.info("qwen comment service: %d/%d posts succeeded", success, len(rows))
    return success

