from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Optional

import requests

from database import postgres as db

logger = logging.getLogger(__name__)


def _compact_qwen_comment(comment: str) -> str:
    max_chars = int(os.environ.get("QWEN_MAX_COMMENT_CHARS", "800"))
    text = (comment or "").strip()
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def _safe_qwen_max_tokens(comment: str, instruction: str) -> int:
    """Estimate a safe completion budget for constrained local backends.

    The local closed-environment profile uses a small model context window.
    Keep completion tokens conservative so prompt + completion stays in bounds.
    """
    model_limit = int(os.environ.get("QWEN_MODEL_MAX_CONTEXT", "512"))
    reserve = int(os.environ.get("QWEN_CONTEXT_RESERVE", "32"))
    min_out = int(os.environ.get("QWEN_MIN_OUTPUT_TOKENS", "96"))
    max_out = int(os.environ.get("QWEN_MAX_OUTPUT_TOKENS", "192"))

    # The qwen service can switch to compact prompts in low-context mode, so
    # use the comment length as the dominant signal here.
    estimated_input_tokens = max(1, (len(comment) + len(instruction) + 160) // 4)
    available = model_limit - estimated_input_tokens - reserve

    if available < min_out:
        return min_out
    return min(max_out, available)


def _log_progress_milestone(current: int, total: int, *, label: str, step: int = 10) -> None:
    if current <= 0:
        return
    if current % step == 0 or current == total:
        logger.info("%s progress: %d/%d ready", label, current, total)


def run_qwen_image_analysis_impl(self, max_images: Optional[int] = None) -> int:
    instruction = ""
    if self.qwen_image_instruction_file:
        p = Path(self.qwen_image_instruction_file)
        if p.is_file():
            instruction = p.read_text(encoding="utf-8").strip()
            logger.info("loaded qwen image instruction from %s (%d chars)", p, len(instruction))

    config = {
        "instruction": instruction,
        "model": self.qwen_image_model,
        # Keep image responses compact in constrained local-vLLM profiles.
        "max_tokens": int(os.environ.get("QWEN_IMAGE_MAX_TOKENS", "96")),
    }
    use_json = bool(self.output_json)

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

    if not self.qwen_service_url:
        if not use_json:
            for img_id, _ in rows:
                with db.connect(self.dsn) as conn:
                    db.mark_image_qwen_failed(conn, image_id=img_id, error="qwen_service_url is not configured")
        logger.warning("No qwen_service_url provided for run_qwen_image_analysis")
        return 0

    success = 0
    handled_ids: set[int] = set()
    total_rows = len(rows)

    def _normalize_qwen_image_payload(parsed: dict) -> dict:
        if not isinstance(parsed, dict):
            return {}
        nested = parsed.get("image_analysis_per_image")
        if isinstance(nested, list) and nested:
            first = nested[0]
            if isinstance(first, dict):
                return first
        return parsed

    for img_id, img_path in rows:
        if not img_path:
            if not use_json:
                with db.connect(self.dsn) as conn:
                    db.mark_image_qwen_failed(conn, image_id=img_id, error="image path is missing")
            handled_ids.add(int(img_id))
            continue

        p = Path(img_path)
        if not p.is_file():
            if not use_json:
                with db.connect(self.dsn) as conn:
                    db.mark_image_qwen_failed(conn, image_id=img_id, error=f"image file not found: {img_path}")
            handled_ids.add(int(img_id))
            continue

        try:
            with open(p, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")

            payload = {"images": [b64], "config": config}
            r = requests.post(f"{self.qwen_service_url.rstrip('/')}/analyze_images", json=payload, timeout=300)
            r.raise_for_status()
            results = r.json().get("results", [])
            if not results:
                raise RuntimeError("qwen image response did not include results")

            parsed_raw = results[0]
            if isinstance(parsed_raw, dict) and "error" in parsed_raw:
                raise RuntimeError(str(parsed_raw["error"]))

            parsed = _normalize_qwen_image_payload(parsed_raw)
            vis_species = parsed.get("visible_species_in_image")
            landscape = parsed.get("landscape_elements")
            human_acts = parsed.get("human_activities_in_image")
            plants_detected = parsed.get("plants_detected")
            animals_detected = parsed.get("animals_detected")
            human_acts_detected = parsed.get("human_activities_detected")

            if use_json:
                self._json_store.setdefault("image_qwen_detail", []).append({
                    "image_id": img_id,
                    "image_summary": parsed.get("image_summary"),
                    "visible_species": vis_species if isinstance(vis_species, list) else None,
                    "landscape_elements": landscape if isinstance(landscape, list) else None,
                    "human_activities": human_acts if isinstance(human_acts, list) else None,
                    "plants_detected": plants_detected if isinstance(plants_detected, list) else None,
                    "animals_detected": animals_detected if isinstance(animals_detected, list) else None,
                    "human_activities_detected": human_acts_detected if isinstance(human_acts_detected, list) else None,
                    "raw_response": json.dumps(parsed_raw, ensure_ascii=False),
                })
            else:
                with db.connect(self.dsn) as conn:
                    db.insert_image_qwen_detail(
                        conn,
                        image_id=img_id,
                        image_summary=parsed.get("image_summary"),
                        visible_species=vis_species if isinstance(vis_species, list) else None,
                        landscape_elements=landscape if isinstance(landscape, list) else None,
                        human_activities=human_acts if isinstance(human_acts, list) else None,
                        plants_detected=plants_detected if isinstance(plants_detected, list) else None,
                        animals_detected=animals_detected if isinstance(animals_detected, list) else None,
                        human_activities_detected=human_acts_detected if isinstance(human_acts_detected, list) else None,
                        raw_response=json.dumps(parsed_raw, ensure_ascii=False),
                    )
                    db.mark_image_qwen_ready(conn, image_id=img_id)

            handled_ids.add(int(img_id))
            success += 1
            _log_progress_milestone(success, total_rows, label="Qwen images", step=100)
        except Exception as exc:
            logger.error("qwen image %d failed: %s", img_id, exc)
            if not use_json:
                with db.connect(self.dsn) as conn:
                    db.mark_image_qwen_failed(conn, image_id=img_id, error=str(exc) or "qwen image analysis failed")
            handled_ids.add(int(img_id))

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

    use_json = bool(self.output_json)

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

    if not self.qwen_service_url:
        if not use_json:
            for post_id, _ in rows:
                with db.connect(self.dsn) as conn:
                    db.mark_post_qwen_failed(conn, post_id=post_id, error="qwen_service_url is not configured")
        logger.warning("No qwen_service_url provided for run_qwen_comment_analysis")
        return 0

    success = 0
    handled_ids: set[int] = set()
    total_rows = len(rows)

    for post_id, comment in rows:
        try:
            compact_comment = _compact_qwen_comment(comment)
            config = {
                "instruction": instruction,
                "model": self.qwen_text_model,
                "max_tokens": _safe_qwen_max_tokens(compact_comment, instruction),
            }
            payload = {"comments": [compact_comment], "config": config}
            r = requests.post(f"{self.qwen_service_url.rstrip('/')}/analyze_users", json=payload, timeout=120)
            r.raise_for_status()
            results = r.json().get("results", [])
            if not results:
                raise RuntimeError("qwen post response did not include results")

            parsed = results[0]
            if isinstance(parsed, dict) and "error" in parsed:
                raise RuntimeError(str(parsed["error"]))

            text_analysis = parsed.get("text_analysis") if isinstance(parsed, dict) else None
            if not isinstance(text_analysis, dict):
                text_analysis = parsed if isinstance(parsed, dict) else {}

            emotions = text_analysis.get("emotions")
            influence = text_analysis.get("influence_of_emotions")
            ts = text_analysis.get("text_species_mentions")
            fs = text_analysis.get("feeling_correlated_to_text_species")
            ta = text_analysis.get("text_activities_or_facilities")
            fa = text_analysis.get("feeling_correlated_to_text_activities_or_facilities")

            if use_json:
                self._json_store.setdefault("post_qwen_detail", []).append({
                    "post_id": post_id,
                    "emotions": emotions if isinstance(emotions, list) else None,
                    "influence_of_emotions": str(influence) if influence else None,
                    "text_species_mentions": ts if isinstance(ts, list) else None,
                    "feeling_correlated_to_text_species": fs if isinstance(fs, list) else None,
                    "text_activities_or_facilities": ta if isinstance(ta, list) else None,
                    "feeling_correlated_to_text_activities_or_facilities": fa if isinstance(fa, list) else None,
                    "raw_response": json.dumps(parsed, ensure_ascii=False),
                })

                sentiment = text_analysis.get("comment_sentiment", {})
                sentiment_score = sentiment.get("score_0_to_1") if isinstance(sentiment, dict) else None
                # Only add sentiment if this post doesn't already have one (e.g., from BERT)
                if sentiment_score is not None and post_id not in existing_sentiment:
                    self._json_store.setdefault("post_sentiment", []).append({"post_id": post_id, "score": float(sentiment_score)})
            else:
                with db.connect(self.dsn) as conn:
                    db.insert_post_qwen_detail(
                        conn,
                        post_id=post_id,
                        emotions=emotions if isinstance(emotions, list) else None,
                        influence_of_emotions=str(influence) if influence else None,
                        text_species_mentions=ts if isinstance(ts, list) else None,
                        feeling_correlated_to_text_species=fs if isinstance(fs, list) else None,
                        text_activities_or_facilities=ta if isinstance(ta, list) else None,
                        feeling_correlated_to_text_activities_or_facilities=fa if isinstance(fa, list) else None,
                        raw_response=json.dumps(parsed, ensure_ascii=False),
                    )

                    sentiment = text_analysis.get("comment_sentiment", {})
                    sentiment_score = sentiment.get("score_0_to_1") if isinstance(sentiment, dict) else None
                    if sentiment_score is not None:
                        db.update_qwen_sentiment(conn, post_id=post_id, score=float(sentiment_score))
                    else:
                        db.mark_post_qwen_ready(conn, post_id=post_id)

            handled_ids.add(int(post_id))
            success += 1
            _log_progress_milestone(success, total_rows, label="Qwen comments", step=1000)
        except Exception as exc:
            logger.error("qwen post %d failed: %s", post_id, exc)
            if not use_json:
                with db.connect(self.dsn) as conn:
                    db.mark_post_qwen_failed(conn, post_id=post_id, error=str(exc) or "qwen comment analysis failed")
            handled_ids.add(int(post_id))

    if not use_json:
        for post_id, _ in rows:
            if int(post_id) in handled_ids:
                continue
            with db.connect(self.dsn) as conn:
                db.mark_post_qwen_failed(conn, post_id=post_id, error="Qwen post result missing or incomplete")

    logger.info("qwen comment service: %d/%d posts succeeded", success, len(rows))
    return success
