from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Optional

import requests

from database import postgres as db

logger = logging.getLogger(__name__)


def analyze_images_impl(self, batch_size: int = 1000, max_batches: Optional[int] = None, workers: int = 1) -> int:
    total_processed = 0
    use_json = bool(self.output_json)

    if use_json:
        all_images = list(self._json_store.get("images", []))
        analyzed_ids = {a.get("image_id") for a in self._json_store.get("image_analysis", [])}
        rows = [(img["id"], img.get("path")) for img in all_images if img["id"] not in analyzed_ids]

        processed_local = 0
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
                r = requests.post(f"{self.bio_service_url.rstrip('/')}/analyze_images", json=payload)
                r.raise_for_status()
                results = r.json().get("results", [])
            elif self._get_bio_model() is not None:
                results = self.bio.analyze_image_blobs(blobs, threshold=0.05)
            else:
                results = [([], []) for _ in blobs]

            for img_id, (species, confidence) in zip(ids, results):
                self._json_store.setdefault("image_analysis", []).append({"image_id": img_id, "species": species, "confidence": confidence})
            processed_local += len(batch)
            if max_batches is not None and processed_local >= batch_size * max_batches:
                break
        return processed_local

    def _worker() -> int:
        processed_local = 0
        with db.connect(self.dsn) as conn:
            while True:
                rows = db.fetch_unanalyzed_images(conn, batch_size)
                if not rows:
                    break
                ids = []
                blobs = []
                for img_id, img_path in rows:
                    ids.append(img_id)
                    if not img_path:
                        logger.warning("image path missing for id %s", img_id)
                        blobs.append(b"")
                        continue
                    p = Path(img_path)
                    if not p.is_file():
                        logger.warning("image file for id %s path %s not found", img_id, img_path)
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
                    r = requests.post(f"{self.bio_service_url.rstrip('/')}/analyze_images", json=payload)
                    r.raise_for_status()
                    results = r.json().get("results", [])
                elif self._get_bio_model() is not None:
                    results = self.bio.analyze_image_blobs(blobs, threshold=0.05)
                else:
                    results = [([], []) for _ in blobs]

                for img_id, (species, confidence) in zip(ids, results):
                    db.update_image_analysis(conn, image_id=img_id, species=species, confidence=confidence)
                processed_local += len(rows)
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
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            post_ids, comments = zip(*batch)

            if self.bert_service_url:
                r = requests.post(f"{self.bert_service_url.rstrip('/')}/analyze_posts", json={"comments": list(comments)})
                r.raise_for_status()
                scores = r.json().get("scores", [])
            else:
                bert_model = self._get_bert_model()
                if bert_model is None:
                    raise RuntimeError("No Bert analyzer available: provide --bert-service-url or remove --skip-bert")
                scores = bert_model.batch_analyze(list(comments))

            for pid, score_dict in zip(post_ids, scores):
                self._json_store.setdefault("post_sentiment", []).append({"post_id": pid, "score": score_dict["sentiment_score"], "label": score_dict.get("sentiment_label", "")})
            local_count += len(batch)
        return local_count

    def _worker() -> int:
        local_count = 0
        with db.connect(self.dsn) as conn:
            while True:
                rows = db.fetch_posts_for_sentiment(conn, limit=batch_size)
                if not rows:
                    break
                post_ids, comments = zip(*rows)

                if self.bert_service_url:
                    r = requests.post(f"{self.bert_service_url.rstrip('/')}/analyze_posts", json={"comments": list(comments)})
                    r.raise_for_status()
                    scores = r.json().get("scores", [])
                else:
                    bert_model = self._get_bert_model()
                    if bert_model is None:
                        raise RuntimeError("No Bert analyzer available: provide --bert-service-url or remove --skip-bert")
                    scores = bert_model.batch_analyze(list(comments))

                for pid, score_dict in zip(post_ids, scores):
                    db.update_bert_sentiment(conn, post_id=pid, score=score_dict["sentiment_score"], label=score_dict.get("sentiment_label", ""))
                local_count += len(rows)
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
