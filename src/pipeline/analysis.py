from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Optional

import requests

from database import postgres as db

logger = logging.getLogger(__name__)


def _post_json_with_retry(
    url: str,
    payload: dict,
    *,
    timeout_seconds: int = 180,
    max_attempts: int = 3,
) -> requests.Response:
    """POST JSON payload with bounded retries to avoid indefinite stage hangs."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(url, json=payload, timeout=timeout_seconds)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_exc = exc
            if attempt >= max_attempts:
                break
            backoff_seconds = attempt * 2
            logger.warning(
                "request failed for %s (attempt %d/%d): %s; retrying in %ds",
                url,
                attempt,
                max_attempts,
                exc,
                backoff_seconds,
            )
            time.sleep(backoff_seconds)

    assert last_exc is not None
    raise last_exc


def _log_progress_milestone(current: int, total: int, *, label: str, step: int = 10) -> None:
    if current <= 0:
        return
    if current % step == 0 or current == total:
        logger.info("%s progress: %d/%d ready", label, current, total)


def analyze_images_impl(self, batch_size: int = 1000, max_batches: Optional[int] = None, workers: int = 1) -> int:
    total_processed = 0
    use_json = bool(self.output_json)

    if use_json:
        all_images = list(self._json_store.get("images", []))
        analyzed_ids = {a.get("image_id") for a in self._json_store.get("image_analysis", [])}
        rows = [(img["id"], img.get("path")) for img in all_images if img["id"] not in analyzed_ids]

        processed_local = 0
        total_rows = len(rows)
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            ids = [r[0] for r in batch]
            blobs = []
            for _, img_path in batch:
                if not img_path:
                    blobs.append(b"")
                    continue
                p = Path(img_path)
                if not p.is_file():
                    logger.warning("image file for id %s path %s not found", _, img_path)
                    blobs.append(b"")
                    continue
                try:
                    with open(p, "rb") as f:
                        blobs.append(f.read())
                except Exception:
                    logger.exception("failed to read image %s", p)
                    blobs.append(b"")

            if self.bio_service_url:
                payload = {"images": [base64.b64encode(b).decode("ascii") for b in blobs]}
                r = _post_json_with_retry(f"{self.bio_service_url.rstrip('/')}/analyze_images", payload, timeout_seconds=240)
                results = r.json().get("results", [])
            elif self._get_bio_model() is not None:
                results = self.bio.analyze_image_blobs(blobs, threshold=0.05)
            else:
                results = [([], []) for _ in blobs]

            for img_id, (species, confidence) in zip(ids, results):
                self._json_store.setdefault("image_analysis", []).append({"image_id": img_id, "species": species, "confidence": confidence})
            processed_local += len(batch)
            _log_progress_milestone(processed_local, total_rows, label="BioClip", step=100)
            if max_batches is not None and processed_local >= batch_size * max_batches:
                break
        return processed_local

    def _worker() -> int:
        processed_local = 0
        with db.connect(self.dsn) as conn:
            db.ensure_schema(conn)
            while True:
                rows = db.claim_images_for_bioclip(conn, batch_size, timeout_seconds=3600)
                if not rows:
                    break
                ids = []
                blobs = []
                for img_id, img_path in rows:
                    ids.append(img_id)
                    if not img_path:
                        logger.warning("image path missing for id %s", img_id)
                        db.mark_image_bioclip_failed(conn, image_id=img_id, error="image path is missing")
                        blobs.append(None)
                        continue
                    p = Path(img_path)
                    if not p.is_file():
                        logger.warning("image file for id %s path %s not found", img_id, img_path)
                        db.mark_image_bioclip_failed(conn, image_id=img_id, error=f"image file not found: {img_path}")
                        blobs.append(None)
                        continue
                    try:
                        with open(p, "rb") as f:
                            blobs.append(f.read())
                    except Exception:
                        logger.exception("failed to read image %s", p)
                        db.mark_image_bioclip_failed(conn, image_id=img_id, error=f"failed to read image: {img_path}")
                        blobs.append(None)

                valid_pairs = [(img_id, blob) for img_id, blob in zip(ids, blobs) if blob is not None]
                if not valid_pairs:
                    continue

                valid_ids = [x[0] for x in valid_pairs]
                valid_blobs = [x[1] for x in valid_pairs]

                try:
                    if self.bio_service_url:
                        payload = {"images": [base64.b64encode(b).decode("ascii") for b in valid_blobs]}
                        r = _post_json_with_retry(f"{self.bio_service_url.rstrip('/')}/analyze_images", payload, timeout_seconds=240)
                        results = r.json().get("results", [])
                    elif self._get_bio_model() is not None:
                        results = self.bio.analyze_image_blobs(valid_blobs, threshold=0.05)
                    else:
                        results = [([], []) for _ in valid_blobs]
                except Exception as exc:
                    logger.exception("BioClip batch failed for %d images", len(valid_ids))
                    err = str(exc) or "BioClip batch failed"
                    for img_id in valid_ids:
                        db.mark_image_bioclip_failed(conn, image_id=img_id, error=err)
                    continue

                for img_id, result in zip(valid_ids, results):
                    try:
                        species, confidence = result
                        db.update_image_analysis(conn, image_id=img_id, species=species, confidence=confidence)
                    except Exception as exc:
                        logger.exception("failed to persist BioClip result for image %s", img_id)
                        db.mark_image_bioclip_failed(conn, image_id=img_id, error=str(exc) or "failed to persist BioClip result")
                if len(results) < len(valid_ids):
                    for img_id in valid_ids[len(results):]:
                        db.mark_image_bioclip_failed(conn, image_id=img_id, error="BioClip returned fewer results than requested")
                processed_local += len(rows)
                if processed_local % 100 == 0:
                    logger.info("BioClip progress: %d images ready in this run", processed_local)
                if max_batches is not None and processed_local >= batch_size * max_batches:
                    break
        return processed_local

    if workers <= 1:
        total_processed = _worker()
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as exe:
            futures = [exe.submit(_worker) for _ in range(workers)]
            for fut in as_completed(futures):
                total_processed += fut.result()
    return total_processed


def analyze_posts_impl(self, batch_size: int = 1000, workers: int = 1) -> int:
    total = 0
    use_json = bool(self.output_json)

    if use_json:
        posts = list(self._json_store.get("posts", []))
        scored_ids = {s.get("post_id") for s in self._json_store.get("post_sentiment", [])}
        rows = [(p["id"], p.get("comment")) for p in posts if p["id"] not in scored_ids and p.get("comment")]

        local_count = 0
        total_rows = len(rows)
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            post_ids, comments = zip(*batch)

            if self.bert_service_url:
                r = _post_json_with_retry(
                    f"{self.bert_service_url.rstrip('/')}/analyze_posts",
                    {"comments": list(comments)},
                    timeout_seconds=240,
                )
                scores = r.json().get("scores", [])
            else:
                bert_model = self._get_bert_model()
                if bert_model is None:
                    raise RuntimeError("No Bert analyzer available: provide --bert-service-url or remove --skip-bert")
                scores = bert_model.batch_analyze(list(comments))

            for pid, score_dict in zip(post_ids, scores):
                self._json_store.setdefault("post_sentiment", []).append({"post_id": pid, "score": score_dict["sentiment_score"], "label": score_dict.get("sentiment_label", "")})
            local_count += len(batch)
            _log_progress_milestone(local_count, total_rows, label="BERT sentiment", step=1000)
        return local_count

    def _worker() -> int:
        local_count = 0
        with db.connect(self.dsn) as conn:
            db.ensure_schema(conn)
            while True:
                rows = db.claim_posts_for_bert(conn, limit=batch_size, timeout_seconds=3600)
                if not rows:
                    break
                post_ids, comments = zip(*rows)

                try:
                    if self.bert_service_url:
                        r = _post_json_with_retry(
                            f"{self.bert_service_url.rstrip('/')}/analyze_posts",
                            {"comments": list(comments)},
                            timeout_seconds=240,
                        )
                        scores = r.json().get("scores", [])
                    else:
                        bert_model = self._get_bert_model()
                        if bert_model is None:
                            raise RuntimeError("No Bert analyzer available: provide --bert-service-url or remove --skip-bert")
                        scores = bert_model.batch_analyze(list(comments))
                except Exception as exc:
                    logger.exception("Bert batch failed for %d posts", len(post_ids))
                    err = str(exc) or "Bert batch failed"
                    for pid in post_ids:
                        db.mark_post_bert_failed(conn, post_id=pid, error=err)
                    continue

                for pid, score_dict in zip(post_ids, scores):
                    try:
                        db.update_bert_sentiment(conn, post_id=pid, score=score_dict["sentiment_score"], label=score_dict.get("sentiment_label", ""))
                    except Exception as exc:
                        logger.exception("failed to persist Bert result for post %s", pid)
                        db.mark_post_bert_failed(conn, post_id=pid, error=str(exc) or "failed to persist Bert result")
                if len(scores) < len(post_ids):
                    for pid in post_ids[len(scores):]:
                        db.mark_post_bert_failed(conn, post_id=pid, error="Bert returned fewer results than requested")
                local_count += len(rows)
                if local_count % 1000 == 0:
                    logger.info("BERT sentiment progress: %d posts ready in this run", local_count)
        return local_count

    if workers <= 1:
        total = _worker()
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as exe:
            futures = [exe.submit(_worker) for _ in range(workers)]
            for fut in as_completed(futures):
                total += fut.result()
    return total
