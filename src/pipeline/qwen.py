from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Optional

import requests

from database import postgres as db

logger = logging.getLogger(__name__)


def run_qwen_image_analysis_impl(self, max_images: Optional[int] = None) -> int:
    instruction = ""
    if self.qwen_image_instruction_file:
        p = Path(self.qwen_image_instruction_file)
        if p.is_file():
            instruction = p.read_text(encoding="utf-8").strip()
            logger.info("loaded qwen image instruction from %s (%d chars)", p, len(instruction))

    config = {"instruction": instruction, "model": self.qwen_image_model}
    use_json = bool(self.output_json)

    if use_json:
        limit = max_images if max_images else 1000000
        all_images = list(self._json_store.get("images", []))
        existing = {d.get("image_id") for d in self._json_store.get("image_qwen_detail", [])}
        rows = [(img["id"], img.get("path")) for img in all_images if img["id"] not in existing][:limit]
    else:
        with db.connect(self.dsn) as conn:
            limit = max_images if max_images else 1000000
            try:
                import sqlite3
            except Exception:
                sqlite3 = None

            if sqlite3 is not None and isinstance(conn, sqlite3.Connection):
                cur = conn.cursor()
                try:
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='image_qwen_detail'")
                    if cur.fetchone() is None:
                        cur.execute("SELECT id, path FROM images ORDER BY id LIMIT ?", (limit,))
                    else:
                        cur.execute("""
                                SELECT i.id, i.path
                                FROM images i
                                LEFT JOIN image_qwen_detail d ON i.id = d.image_id
                                WHERE d.id IS NULL
                                ORDER BY i.id
                                LIMIT ?
                                """, (limit,))
                    rows = cur.fetchall()
                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass
            else:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT i.id, i.path
                        FROM images i
                        LEFT JOIN image_qwen_detail d ON i.id = d.image_id
                        WHERE d.id IS NULL
                        ORDER BY i.id
                        LIMIT %s
                        """,
                        (limit,)
                    )
                    rows = cur.fetchall()

    if not rows:
        logger.info("no unanalyzed images found for Qwen")
        return 0

    success = 0
    if self.qwen_service_url:
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
                continue
            p = Path(img_path)
            if not p.is_file():
                continue

            try:
                with open(p, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")

                payload = {"images": [b64], "config": config}
                r = requests.post(f"{self.qwen_service_url.rstrip('/')}/analyze_images", json=payload, timeout=300)
                r.raise_for_status()
                results = r.json().get("results", [])
                if results:
                    parsed_raw = results[0]
                    if isinstance(parsed_raw, dict) and "error" in parsed_raw:
                        logger.warning("qwen image %d returned error: %s", img_id, parsed_raw["error"])
                    else:
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

                        success += 1
            except Exception as exc:
                logger.error("qwen image %d failed: %s", img_id, exc)

        logger.info("qwen image service: %d/%d images succeeded", success, len(rows))
        return success
    else:
        logger.warning("No qwen_service_url provided for run_qwen_image_analysis")
        return 0


def run_qwen_comment_analysis_impl(self, max_posts: Optional[int] = None) -> int:
    instruction = ""
    if self.qwen_comment_instruction_file:
        p = Path(self.qwen_comment_instruction_file)
        if p.is_file():
            instruction = p.read_text(encoding="utf-8").strip()
            logger.info("loaded qwen comment instruction from %s (%d chars)", p, len(instruction))

    config = {"instruction": instruction, "model": self.qwen_text_model}
    use_json = bool(self.output_json)
    if use_json:
        limit = max_posts if max_posts else 1000000
        posts = list(self._json_store.get("posts", []))
        existing = {d.get("post_id") for d in self._json_store.get("post_qwen_detail", [])}
        rows = [(p["id"], p.get("comment")) for p in posts if p["id"] not in existing and p.get("comment")][:limit]
    else:
        with db.connect(self.dsn) as conn:
            limit = max_posts if max_posts else 1000000
            try:
                import sqlite3
            except Exception:
                sqlite3 = None

            if sqlite3 is not None and isinstance(conn, sqlite3.Connection):
                cur = conn.cursor()
                try:
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='post_qwen_detail'")
                    if cur.fetchone() is None:
                        cur.execute("SELECT id, comment FROM posts WHERE comment IS NOT NULL AND TRIM(comment) != '' ORDER BY id LIMIT ?", (limit,))
                    else:
                        cur.execute("""
                                SELECT p.id, p.comment
                                FROM posts p
                                LEFT JOIN post_qwen_detail d ON p.id = d.post_id
                                WHERE d.id IS NULL AND p.comment IS NOT NULL AND TRIM(p.comment) != ''
                                ORDER BY p.id
                                LIMIT ?
                                """, (limit,))
                    rows = cur.fetchall()
                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass
            else:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT p.id, p.comment
                        FROM posts p
                        LEFT JOIN post_qwen_detail d ON p.id = d.post_id
                        WHERE d.id IS NULL AND p.comment IS NOT NULL AND TRIM(p.comment) != ''
                        ORDER BY p.id
                        LIMIT %s
                        """,
                        (limit,)
                    )
                    rows = cur.fetchall()

    if not rows:
        logger.info("no unanalyzed posts found for Qwen")
        return 0

    success = 0
    if self.qwen_service_url:
        for post_id, comment in rows:
            try:
                payload = {"comments": [comment], "config": config}
                r = requests.post(f"{self.qwen_service_url.rstrip('/')}/analyze_users", json=payload, timeout=120)
                r.raise_for_status()
                results = r.json().get("results", [])
                if results:
                    parsed = results[0]
                    if "error" in parsed:
                        logger.warning("qwen post %d returned error: %s", post_id, parsed["error"])
                    else:
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
                            if sentiment_score is not None:
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

                        success += 1
            except Exception as exc:
                logger.error("qwen post %d failed: %s", post_id, exc)

        logger.info("qwen comment service: %d/%d posts succeeded", success, len(rows))
        return len(rows)
    else:
        logger.warning("No qwen_service_url provided for run_qwen_comment_analysis")
        return 0
