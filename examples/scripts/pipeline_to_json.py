#!/usr/bin/env python3
"""
Lightweight pipeline-to-JSON helper for quick testing without a database.

Usage examples:
  # using running services
  python examples/scripts/pipeline_to_json.py \
    --image-folder data/split_1/53深圳市宝安区西乡公园/images \
    --comments-file examples/scripts/sample_comments.txt \
    --bio-service-url http://127.0.0.1:5000 \
    --bert-service-url http://127.0.0.1:5001 \
    --qwen-service-url http://127.0.0.1:5002 \
    --out-dir tmp/results

  # quick local stub mode (no services)
  python examples/scripts/pipeline_to_json.py --image-folder data/split_1/... --comments-file examples/scripts/sample_comments.txt --out-dir tmp/results

This script will write `images_results.json` and `comments_results.json` into the output directory.
"""

import argparse
import base64
import json
import os
from pathlib import Path
from typing import List

import requests


def find_images(folder: Path, limit: int = 10) -> List[Path]:
    imgs = []
    if not folder or not folder.exists():
        return imgs
    for p in folder.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"):
            imgs.append(p)
            if len(imgs) >= limit:
                break
    return imgs


def read_comments(file: Path, limit: int = 100) -> List[str]:
    if not file or not file.exists():
        return []
    with file.open("r", encoding="utf-8") as fh:
        lines = [l.strip() for l in fh if l.strip()]
    return lines[:limit]


def stub_image_analysis(encoded_images: List[str]):
    results = []
    for _ in encoded_images:
        results.append({"species": [], "confidence": 0.0})
    return results


def stub_comment_analysis(comments: List[str]):
    results = []
    for _ in comments:
        results.append({"sentiment_score": 0.5, "sentiment_label": "neutral"})
    return results


def call_service(url: str, endpoint: str, payload: dict, timeout: int = 60):
    r = requests.post(f"{url.rstrip('/')}/{endpoint.lstrip('/')}", json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def analyze_images(image_paths: List[Path], bio_url: str = None, qwen_url: str = None):
    encoded = []
    for p in image_paths:
        try:
            b = p.read_bytes()
            encoded.append(base64.b64encode(b).decode("ascii"))
        except Exception as e:
            encoded.append("")
    images_results = []
    if bio_url:
        try:
            payload = {"images": encoded}
            resp = call_service(bio_url, "analyze_images", payload)
            images_results = resp.get("results", [])
        except Exception as e:
            print(f"Bio service call failed: {e}")
            images_results = stub_image_analysis(encoded)
    else:
        images_results = stub_image_analysis(encoded)

    # Optionally call qwen for richer analysis per image
    qwen_results = []
    if qwen_url:
        try:
            payload = {"images": encoded, "config": {}}
            resp = call_service(qwen_url, "analyze_images", payload)
            qwen_results = resp.get("results", [])
        except Exception as e:
            print(f"Qwen service call failed: {e}")
            qwen_results = [{} for _ in encoded]
    else:
        qwen_results = [{} for _ in encoded]

    combined = []
    for p, bio_r, qwen_r in zip(image_paths, images_results, qwen_results):
        combined.append({"path": str(p), "bio": bio_r, "qwen": qwen_r})
    return combined


def analyze_comments(comments: List[str], bert_url: str = None, qwen_url: str = None):
    if bert_url:
        try:
            payload = {"comments": comments}
            resp = call_service(bert_url, "analyze_posts", payload)
            return resp.get("scores", [])
        except Exception as e:
            print(f"Bert service call failed: {e}")
            return stub_comment_analysis(comments)
    elif qwen_url:
        try:
            payload = {"comments": comments, "config": {}}
            resp = call_service(qwen_url, "analyze_comments", payload)
            return resp.get("results", [])
        except Exception as e:
            print(f"Qwen comment call failed: {e}")
            return stub_comment_analysis(comments)
    else:
        return stub_comment_analysis(comments)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--image-folder", type=Path, default=None, help="Folder with images to analyze")
    p.add_argument("--comments-file", type=Path, default=None, help="File with one comment per line")
    p.add_argument("--bio-service-url", default=None, help="BioClip service URL (http://host:port)")
    p.add_argument("--bert-service-url", default=None, help="Bert service URL (http://host:port)")
    p.add_argument("--qwen-service-url", default=None, help="Qwen service URL (http://host:port)")
    p.add_argument("--out-dir", type=Path, required=True, help="Output directory for JSON results")
    p.add_argument("--image-limit", type=int, default=10)
    p.add_argument("--comment-limit", type=int, default=100)
    args = p.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    images = find_images(args.image_folder, limit=args.image_limit) if args.image_folder else []
    comments = read_comments(args.comments_file, limit=args.comment_limit) if args.comments_file else []

    print(f"Found {len(images)} images and {len(comments)} comments")

    img_results = analyze_images(images, bio_url=args.bio_service_url, qwen_url=args.qwen_service_url)
    comments_results = analyze_comments(comments, bert_url=args.bert_service_url, qwen_url=args.qwen_service_url)

    images_out = args.out_dir / "images_results.json"
    comments_out = args.out_dir / "comments_results.json"

    with images_out.open("w", encoding="utf-8") as fh:
        json.dump(img_results, fh, ensure_ascii=False, indent=2)

    with comments_out.open("w", encoding="utf-8") as fh:
        json.dump(comments_results, fh, ensure_ascii=False, indent=2)

    print(f"Wrote {images_out} and {comments_out}")


if __name__ == "__main__":
    main()
