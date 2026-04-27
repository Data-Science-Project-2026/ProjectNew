#!/usr/bin/env python3
"""
HPC-friendly wrapper for running the complete pipeline with JSON output (no PostgreSQL).

This script orchestrates ingestion + analysis using the Pipeline class in JSON mode,
producing all results in a single JSON file without requiring database access.

Usage examples:

  # Basic usage with CSV and images, output to JSON:
  python examples/scripts/run_json_pipeline.py \\
    --csv-folder data/split_1/53æ·±åœ³å¸‚å®å®‰åŒºè¥¿ä¹¡å…¬å›­ \\
    --image-folder data/split_1/53æ·±åœ³å¸‚å®å®‰åŒºè¥¿ä¹¡å…¬å›­/images \\
    --output results.json

  # With Qwen models (requires service URLs or local installation):
  python examples/scripts/run_json_pipeline.py \\
    --csv-folder data/split_1/... \\
    --image-folder data/split_1/.../images \\
    --qwen-service-url http://localhost:5002 \\
    --output results.json \\
    --run-qwen

  # With BioClip service:
  python examples/scripts/run_json_pipeline.py \\
    --csv-folder data/split_1/... \\
    --image-folder data/split_1/.../images \\
    --bio-service-url http://localhost:5000 \\
    --output results.json

  # Skip expensive models and just do ingestion:
  python examples/scripts/run_json_pipeline.py \\
    --csv-folder data/split_1/... \\
    --image-folder data/split_1/.../images \\
    --output results.json \\
    --skip-bio --skip-bert --skip-qwen
        proc_group.add_argument(
            "--qwen-workers",
            type=int,
            default=4,
            help="Number of workers for concurrent Qwen requests",
        )

  # Process only first N posts/images:
  python examples/scripts/run_json_pipeline.py \\
    --csv-folder data/split_1/... \\
    --image-folder data/split_1/.../images \\
    --output results.json \\
    --max-posts 100 \\
    --max-images 200

If running on HPC:
- Set service URLs to point to running Singularity instances or remote services
- Use --skip-* flags to disable local model loading (required if model libs not installed)
- In no-install environments, use module-loaded Python and/or run inside a prebuilt .sif image
- Redirect output to a log file for job monitoring: > pipeline.log 2>&1
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# Ensure src is in path for imports
src_dir = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from pipeline.orchestrator import Pipeline

logger = logging.getLogger(__name__)


def _run_compose_cmd(project_dir: Path, env_file: Optional[str], args: list[str]) -> None:
    cmd = ["docker", "compose"]
    if env_file:
        cmd.extend(["--env-file", env_file])
    cmd.extend(args)
    logger.info("compose cmd: %s", " ".join(cmd))
    subprocess.run(cmd, cwd=str(project_dir), check=True)


def _wait_for_http_ok(url: str, timeout_seconds: int = 600) -> None:
    t0 = time.time()
    while True:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                return
        except requests.RequestException:
            pass
        if time.time() - t0 > timeout_seconds:
            raise TimeoutError(f"Timeout waiting for service at {url}")
        time.sleep(3)


def _stop_qwen_services(project_dir: Path, env_file: Optional[str], service_names: list[str]) -> None:
    try:
        _run_compose_cmd(project_dir, env_file, ["stop", *service_names])
    except Exception as exc:
        logger.warning("could not stop qwen services (%s); continuing", exc)


def _start_qwen_services_and_wait(
    project_dir: Path,
    env_file: Optional[str],
    service_names: list[str],
    qwen_service_url: str,
    timeout_seconds: int = 600,
) -> None:
    _run_compose_cmd(project_dir, env_file, ["up", "-d", *service_names])
    health_url = f"{qwen_service_url.rstrip('/')}/"
    logger.info("waiting for qwen service health at %s", health_url)
    _wait_for_http_ok(health_url, timeout_seconds=timeout_seconds)


def _write_checkpoint(
    pipeline: Pipeline,
    output_json: Path,
    *,
    stage: str,
    status: str,
    posts_ingested: int,
    images_ingested: int,
    last_error: Optional[str] = None,
) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    pipeline._json_store["pipeline_run"] = {
        "stage": stage,
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "posts_ingested": posts_ingested,
        "images_ingested": images_ingested,
        "last_error": last_error,
    }
    pipeline.dump_results(str(output_json))
    logger.info("checkpoint written to %s after stage '%s'", output_json, stage)


def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> None:
    """Configure logging to console and optional file."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)
    
    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def run_pipeline_json_mode(
    csv_folder: Optional[Path],
    image_folders,
    output_json: Path,
    max_posts: Optional[int],
    max_images: Optional[int],
    batch_size: int,
    workers: int,
    bio_service_url: Optional[str],
    bert_service_url: Optional[str],
    qwen_service_url: Optional[str],
    run_bio: bool,
    run_bert: bool,
    run_qwen: bool,
    qwen_image_model: str,
    qwen_text_model: str,
    qwen_image_instruction_file: Optional[str],
    qwen_comment_instruction_file: Optional[str],
    debug: bool,
    lazy_load_qwen: bool,
    compose_project_dir: Path,
    compose_env_file: Optional[str],
    stop_qwen_after_run: bool,
) -> int:
    """Run the complete pipeline in JSON mode (no PostgreSQL)."""
    
    logger.info("=" * 70)
    logger.info("Running Pipeline in JSON Mode")
    logger.info("=" * 70)
    logger.info("Output JSON: %s", output_json)
    logger.info("CSV folder: %s", csv_folder)
    logger.info("Image folders: %s", image_folders)
    logger.info("Max posts: %s", max_posts)
    logger.info("Max images: %s", max_images)
    logger.info("Skip BioClip: %s", not run_bio)
    logger.info("Skip BERT: %s", not run_bert)
    logger.info("Skip Qwen: %s", not run_qwen)
    logger.info("Lazy-load Qwen services: %s", lazy_load_qwen)
    logger.info("=" * 70)

    qwen_services = ["local-llm", "qwen"]

    if lazy_load_qwen and run_qwen:
        if not qwen_service_url:
            logger.error("--lazy-load-qwen requires --qwen-service-url")
            return 1
        logger.info("Lazy mode: stopping qwen services before BioClip/BERT stages")
        _stop_qwen_services(compose_project_dir, compose_env_file, qwen_services)
    
    # Initialize pipeline in JSON mode (no DSN needed)
    pipeline = Pipeline(
        dsn="",  # unused in JSON mode
        output_json=str(output_json),
        bio_clip_args={
            "species_tokens_path": Path(src_dir) / "models" / "BioClip" / "species_tokens_latin.pt",
            "species_names_path": Path(src_dir) / "models" / "BioClip" / "species_names_latin.txt",
            "use_half": False,
            "text_batch_size": 4048,
        },
        qwen_args={
            "image_model": qwen_image_model,
            "text_model": qwen_text_model,
            "image_instruction_file": qwen_image_instruction_file,
            "comment_instruction_file": qwen_comment_instruction_file,
            "workers": args.qwen_workers,
        },
        bio_service_url=bio_service_url,
        bert_service_url=bert_service_url,
        qwen_service_url=qwen_service_url,
        skip_bio=not run_bio,
        skip_bert=not run_bert,
        skip_qwen=not run_qwen,
    )

    posts_ingested = 0
    images_ingested = 0
    _write_checkpoint(
        pipeline,
        output_json,
        stage="initialized",
        status="running",
        posts_ingested=posts_ingested,
        images_ingested=images_ingested,
    )
    
    # Stage 1: Ingest posts from CSV files
    if csv_folder and csv_folder.exists():
        logger.info("Stage 1: Ingesting posts from CSV...")
        t0 = time.perf_counter()
        try:
            posts_ingested = pipeline.ingest_posts(
                csv_folder,
                images_root=image_folders[0] if image_folders else None,
                max_posts=max_posts,
                debug=debug,
            )
            dt = time.perf_counter() - t0
            logger.info("âœ“ Ingested %d posts in %.1f seconds", posts_ingested, dt)
            _write_checkpoint(
                pipeline,
                output_json,
                stage="posts_ingested",
                status="running",
                posts_ingested=posts_ingested,
                images_ingested=images_ingested,
            )
        except Exception as e:
            logger.error("âœ— Post ingestion failed: %s", e, exc_info=True)
            _write_checkpoint(
                pipeline,
                output_json,
                stage="post_ingestion_failed",
                status="failed",
                posts_ingested=posts_ingested,
                images_ingested=images_ingested,
                last_error=str(e),
            )
            return 1
    else:
        logger.warning("No CSV folder provided or folder not found, skipping post ingestion")
        _write_checkpoint(
            pipeline,
            output_json,
            stage="posts_skipped",
            status="running",
            posts_ingested=posts_ingested,
            images_ingested=images_ingested,
        )
    
    # Stage 2: Ingest images
    if image_folders:
        logger.info("Stage 2: Ingesting images...")
        t0 = time.perf_counter()
        try:
            images_ingested = pipeline.ingest_images(
                [Path(f) for f in image_folders if Path(f).exists()],
                image_storage=None,  # in JSON mode, we store paths, not copies
            )
            dt = time.perf_counter() - t0
            logger.info("âœ“ Ingested %d images in %.1f seconds", images_ingested, dt)
            _write_checkpoint(
                pipeline,
                output_json,
                stage="images_ingested",
                status="running",
                posts_ingested=posts_ingested,
                images_ingested=images_ingested,
            )
        except Exception as e:
            logger.error("âœ— Image ingestion failed: %s", e, exc_info=True)
            _write_checkpoint(
                pipeline,
                output_json,
                stage="image_ingestion_failed",
                status="failed",
                posts_ingested=posts_ingested,
                images_ingested=images_ingested,
                last_error=str(e),
            )
            return 1
    else:
        logger.warning("No image folders provided, skipping image ingestion")
        _write_checkpoint(
            pipeline,
            output_json,
            stage="images_skipped",
            status="running",
            posts_ingested=posts_ingested,
            images_ingested=images_ingested,
        )
    
    # Stage 3: Analyze images (BioClip)
    if run_bio and images_ingested > 0:
        logger.info("Stage 3: Analyzing images with BioClip...")
        t0 = time.perf_counter()
        try:
            analyzed = pipeline.analyze_images(batch_size=batch_size, workers=workers)
            dt = time.perf_counter() - t0
            logger.info("âœ“ Analyzed %d images in %.1f seconds", analyzed, dt)
            _write_checkpoint(
                pipeline,
                output_json,
                stage="bio_analysis_completed",
                status="running",
                posts_ingested=posts_ingested,
                images_ingested=images_ingested,
            )
        except Exception as e:
            logger.error("âœ— Image analysis failed: %s", e, exc_info=True)
            _write_checkpoint(
                pipeline,
                output_json,
                stage="bio_analysis_failed",
                status="running",
                posts_ingested=posts_ingested,
                images_ingested=images_ingested,
                last_error=str(e),
            )
            # don't return, continue to other stages
    
    # Stage 4: Analyze posts (BERT sentiment)
    if run_bert and posts_ingested > 0:
        logger.info("Stage 4: Analyzing posts with BERT sentiment...")
        t0 = time.perf_counter()
        try:
            analyzed = pipeline.analyze_posts(batch_size=batch_size, workers=workers)
            dt = time.perf_counter() - t0
            logger.info("âœ“ Analyzed %d posts in %.1f seconds", analyzed, dt)
            _write_checkpoint(
                pipeline,
                output_json,
                stage="bert_analysis_completed",
                status="running",
                posts_ingested=posts_ingested,
                images_ingested=images_ingested,
            )
        except Exception as e:
            logger.error("âœ— Post sentiment analysis failed: %s", e, exc_info=True)
            _write_checkpoint(
                pipeline,
                output_json,
                stage="bert_analysis_failed",
                status="running",
                posts_ingested=posts_ingested,
                images_ingested=images_ingested,
                last_error=str(e),
            )
            # don't return, continue to other stages
    
    # Stage 5A: Qwen image analysis
    if lazy_load_qwen and run_qwen:
        try:
            logger.info("Lazy mode: starting qwen services right before Qwen stages")
            _start_qwen_services_and_wait(
                compose_project_dir,
                compose_env_file,
                qwen_services,
                qwen_service_url,
            )
        except Exception as e:
            logger.error("âœ— Failed to start qwen services in lazy mode: %s", e, exc_info=True)
            _write_checkpoint(
                pipeline,
                output_json,
                stage="qwen_service_start_failed",
                status="failed",
                posts_ingested=posts_ingested,
                images_ingested=images_ingested,
                last_error=str(e),
            )
            return 1

    if run_qwen and images_ingested > 0:
        logger.info("Stage 5A: Analyzing images with Qwen...")
        t0 = time.perf_counter()
        try:
            qwen_img = pipeline.run_qwen_image_analysis(max_images=max_images)
            dt = time.perf_counter() - t0
            logger.info("âœ“ Qwen analyzed %d images in %.1f seconds", qwen_img, dt)
            _write_checkpoint(
                pipeline,
                output_json,
                stage="qwen_image_analysis_completed",
                status="running",
                posts_ingested=posts_ingested,
                images_ingested=images_ingested,
            )
        except Exception as e:
            logger.error("âœ— Qwen image analysis failed: %s", e, exc_info=True)
            _write_checkpoint(
                pipeline,
                output_json,
                stage="qwen_image_analysis_failed",
                status="running",
                posts_ingested=posts_ingested,
                images_ingested=images_ingested,
                last_error=str(e),
            )
            # don't return, continue to other stages
    
    # Stage 5B: Qwen comment analysis
    if run_qwen and posts_ingested > 0:
        logger.info("Stage 5B: Analyzing comments with Qwen...")
        t0 = time.perf_counter()
        try:
            qwen_post = pipeline.run_qwen_comment_analysis(max_posts=max_posts)
            dt = time.perf_counter() - t0
            logger.info("âœ“ Qwen analyzed %d comments in %.1f seconds", qwen_post, dt)
            _write_checkpoint(
                pipeline,
                output_json,
                stage="qwen_comment_analysis_completed",
                status="running",
                posts_ingested=posts_ingested,
                images_ingested=images_ingested,
            )
        except Exception as e:
            logger.error("âœ— Qwen comment analysis failed: %s", e, exc_info=True)
            _write_checkpoint(
                pipeline,
                output_json,
                stage="qwen_comment_analysis_failed",
                status="running",
                posts_ingested=posts_ingested,
                images_ingested=images_ingested,
                last_error=str(e),
            )
            # don't return, continue to other stages

    if lazy_load_qwen and run_qwen and stop_qwen_after_run:
        logger.info("Lazy mode: stopping qwen services after Qwen stages")
        _stop_qwen_services(compose_project_dir, compose_env_file, qwen_services)
    
    # Stage 6: Dump results to JSON
    logger.info("Stage 6: Writing results to JSON...")
    try:
        _write_checkpoint(
            pipeline,
            output_json,
            stage="completed",
            status="completed",
            posts_ingested=posts_ingested,
            images_ingested=images_ingested,
        )
        logger.info("âœ“ Results written to %s", output_json)
    except Exception as e:
        logger.error("âœ— Failed to write results: %s", e, exc_info=True)
        return 1
    
    # Summary
    logger.info("=" * 70)
    logger.info("Pipeline completed successfully!")
    logger.info("Summary:")
    logger.info("  - Posts ingested: %d", posts_ingested)
    logger.info("  - Images ingested: %d", images_ingested)
    logger.info("  - Results file: %s", output_json)
    logger.info("=" * 70)
    
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the complete pipeline with JSON output (no PostgreSQL required)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    # Input data
    input_group = parser.add_argument_group("input data")
    input_group.add_argument(
        "--csv-folder",
        type=Path,
        default=None,
        help="Folder containing CSV files with posts/comments",
    )
    input_group.add_argument(
        "--image-folder",
        type=Path,
        action="append",
        dest="image_folders",
        default=[],
        help="Folder(s) containing images (can be specified multiple times)",
    )
    input_group.add_argument(
        "--max-posts",
        type=int,
        default=None,
        help="Maximum number of posts to ingest",
    )
    input_group.add_argument(
        "--max-images",
        type=int,
        default=None,
        help="Maximum number of images to process per stage",
    )
    
    # Output
    output_group = parser.add_argument_group("output")
    output_group.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write results JSON file",
    )
    output_group.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Optional log file path (in addition to console output)",
    )
    
    # Processing options
    proc_group = parser.add_argument_group("processing")
    proc_group.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch size for processing (default: 1000)",
    )
    proc_group.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker threads (default: 1)",
    )
    proc_group.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging and sample posts output",
    )
    
    # Model selection
    model_group = parser.add_argument_group("models")
    model_group.add_argument(
        "--run-bio",
        action="store_true",
        default=False,
        help="Run BioClip image analysis (default: skip)",
    )
    model_group.add_argument(
        "--run-bert",
        action="store_true",
        default=False,
        help="Run BERT sentiment analysis (default: skip)",
    )
    model_group.add_argument(
        "--run-qwen",
        action="store_true",
        default=False,
        help="Run Qwen multi-modal analysis (default: skip)",
    )
    model_group.add_argument(
        "--skip-bio",
        action="store_true",
        help="Skip BioClip (useful when model deps not installed)",
    )
    model_group.add_argument(
        "--skip-bert",
        action="store_true",
        help="Skip BERT (useful when model deps not installed)",
    )
    model_group.add_argument(
        "--skip-qwen",
        proc_group.add_argument(
            "--qwen-workers",
            type=int,
            default=4,
            help="Number of workers for concurrent Qwen requests",
        )
        action="store_true",
        help="Skip Qwen (useful when model deps not installed)",
    )
    
    # Service URLs
    svc_group = parser.add_argument_group("services")
    svc_group.add_argument(
        "--bio-service-url",
        type=str,
        default=None,
        help="BioClip service URL (e.g. http://localhost:5000); overrides local model",
    )
    svc_group.add_argument(
        "--bert-service-url",
        type=str,
        default=None,
        help="BERT service URL (e.g. http://localhost:5001); overrides local model",
    )
    svc_group.add_argument(
        "--qwen-service-url",
        type=str,
        default=None,
        help="Qwen service URL (e.g. http://localhost:5002); overrides local model",
    )
    
    # Qwen configuration
    qwen_group = parser.add_argument_group("qwen configuration")
    qwen_group.add_argument(
        "--qwen-image-model",
        type=str,
        default="Qwen/Qwen3.5-4B",
        help="Qwen model name for image analysis (default: Qwen/Qwen3.5-4B)",
    )
    qwen_group.add_argument(
        "--qwen-text-model",
        type=str,
        default="Qwen/Qwen3.5-4B",
        help="Qwen model name for text/comment analysis (default: Qwen/Qwen3.5-4B)",
    )
    qwen_group.add_argument(
        "--qwen-image-instruction-file",
        type=str,
        default=None,
        help="Path to file with custom image analysis instructions for Qwen",
    )
    qwen_group.add_argument(
        "--qwen-comment-instruction-file",
        type=str,
        default=None,
        help="Path to file with custom comment analysis instructions for Qwen",
    )

    lifecycle_group = parser.add_argument_group("qwen service lifecycle")
    lifecycle_group.add_argument(
        "--lazy-load-qwen",
        action="store_true",
        help="If set, stop local-llm/qwen before BioClip+BERT and start them only before Qwen stages",
    )
    lifecycle_group.add_argument(
        "--compose-project-dir",
        type=Path,
        default=Path("."),
        help="Directory where docker compose is run for lazy Qwen lifecycle (default: current directory)",
    )
    lifecycle_group.add_argument(
        "--compose-env-file",
        type=str,
        default=None,
        help="Optional env file passed to docker compose for lazy Qwen lifecycle",
    )
    lifecycle_group.add_argument(
        "--stop-qwen-after-run",
        action="store_true",
        help="In lazy mode, also stop local-llm/qwen after Qwen stages complete",
    )
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(
        level="DEBUG" if args.debug else "INFO",
        log_file=args.log_file,
    )
    
    logger.debug("Command-line arguments: %s", args)
    
    # Validate inputs
    if args.csv_folder and not args.csv_folder.exists():
        logger.error("CSV folder does not exist: %s", args.csv_folder)
        return 1
    
    image_folders = [f for f in args.image_folders if Path(f).exists()]
    if args.image_folders and not image_folders:
        logger.error("No valid image folders found from: %s", args.image_folders)
        return 1
    
    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)
    
    # Determine which models to run
    run_bio = args.run_bio and not args.skip_bio
    run_bert = args.run_bert and not args.skip_bert
    run_qwen = args.run_qwen and not args.skip_qwen
    
    if not run_bio and not run_bert and not run_qwen:
        logger.warning("No models selected to run; will only perform ingestion")
    
    # Run pipeline
    try:
        return run_pipeline_json_mode(
            csv_folder=args.csv_folder,
            image_folders=image_folders,
            output_json=args.output,
            max_posts=args.max_posts,
            max_images=args.max_images,
            batch_size=args.batch_size,
            workers=args.workers,
            bio_service_url=args.bio_service_url,
            bert_service_url=args.bert_service_url,
            qwen_service_url=args.qwen_service_url,
            run_bio=run_bio,
            run_bert=run_bert,
            run_qwen=run_qwen,
            qwen_image_model=args.qwen_image_model,
            qwen_text_model=args.qwen_text_model,
            qwen_image_instruction_file=args.qwen_image_instruction_file,
            qwen_comment_instruction_file=args.qwen_comment_instruction_file,
            debug=args.debug,
            lazy_load_qwen=args.lazy_load_qwen,
            compose_project_dir=args.compose_project_dir,
            compose_env_file=args.compose_env_file,
            stop_qwen_after_run=args.stop_qwen_after_run,
        )
    except KeyboardInterrupt:
        logger.warning("Pipeline interrupted by user")
        return 130
    except Exception as e:
        logger.exception("Pipeline failed with exception")
        return 1


if __name__ == "__main__":
    sys.exit(main())

