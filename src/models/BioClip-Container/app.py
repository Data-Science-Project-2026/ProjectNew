import os
import base64
import logging
import subprocess
import sys
import time
from pathlib import Path
from flask import Flask, request, jsonify

# ensure that the parent package is on the path; when building the Docker
# image we will copy the entire workspace and set PYTHONPATH accordingly.

from models.BioClip.model import BioClipModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

SRC_ROOT = Path(__file__).resolve().parents[2]
BIOCLIP_DIR = SRC_ROOT / "models" / "BioClip"
TOKENIZE_SCRIPT = BIOCLIP_DIR / "tokenize_excel_species.py"


def _log_stage(stage_name: str, started_at: float) -> None:
    logger.info("Startup stage complete: %s (%.2fs)", stage_name, time.perf_counter() - started_at)

@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

# configuration from environment variables
SPECIES_TOKENS = os.environ.get("SPECIES_TOKENS_PATH", str(BIOCLIP_DIR / "species_tokens_latin.pt"))
SPECIES_NAMES = os.environ.get("SPECIES_NAMES_PATH", str(BIOCLIP_DIR / "species_names_latin.txt"))
SPECIES_SOURCE_XLSX = os.environ.get("SPECIES_SOURCE_XLSX", str(BIOCLIP_DIR / "Species_China.xlsx"))
BIO_MODEL_NAME = os.environ.get("BIO_MODEL_NAME", "ViT-L-14")
BIO_MODEL_CHECKPOINT_PATH = os.environ.get(
    "BIO_MODEL_CHECKPOINT_PATH",
    str(BIOCLIP_DIR / "open_clip_pytorch_model.bin"),
)
BIO_ALLOW_REMOTE_MODEL = bool(
    os.environ.get("BIO_ALLOW_REMOTE_MODEL", "0").lower() in ("1", "true", "yes")
)
USE_HALF = bool(os.environ.get("USE_HALF", "False").lower() in ("1", "true"))
TEXT_BATCH_SIZE = int(os.environ.get("TEXT_BATCH_SIZE", 512))
IMAGE_BATCH_SIZE = int(os.environ.get("IMAGE_BATCH_SIZE", 64))


def _ensure_species_assets() -> None:
    stage_started = time.perf_counter()
    tokens_path = Path(SPECIES_TOKENS)
    names_path = Path(SPECIES_NAMES)
    xlsx_path = Path(SPECIES_SOURCE_XLSX)

    logger.info(
        "Checking species assets: tokens=%s names=%s source_xlsx=%s",
        tokens_path,
        names_path,
        xlsx_path,
    )

    if tokens_path.exists() and names_path.exists():
        logger.info(
            "Species assets already exist (tokens_bytes=%d names_bytes=%d)",
            tokens_path.stat().st_size,
            names_path.stat().st_size,
        )
        _log_stage("ensure species assets", stage_started)
        return

    if not xlsx_path.exists():
        raise FileNotFoundError(
            f"Missing species source file: {xlsx_path}. Cannot generate BioClip token assets."
        )

    tokens_path.parent.mkdir(parents=True, exist_ok=True)
    names_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Species assets missing; generating with %s", TOKENIZE_SCRIPT)
    tokenize_started = time.perf_counter()
    subprocess.run(
        [
            sys.executable,
            str(TOKENIZE_SCRIPT),
            str(xlsx_path),
            str(names_path),
            str(tokens_path),
        ],
        check=True,
    )
    _log_stage("tokenize species assets", tokenize_started)
    _log_stage("ensure species assets", stage_started)

# initialize the BioClip model; failure to load the token files
# should not crash the entire container during development.  we
# catch the FileNotFoundError and fall back to a dummy instance.
try:
    boot_started = time.perf_counter()

    _ensure_species_assets()

    model_init_started = time.perf_counter()
    logger.info(
        "Starting BioClip model with species_tokens=%s species_names=%s species_xlsx=%s checkpoint=%s allow_remote=%s",
        SPECIES_TOKENS,
        SPECIES_NAMES,
        SPECIES_SOURCE_XLSX,
        BIO_MODEL_CHECKPOINT_PATH,
        BIO_ALLOW_REMOTE_MODEL,
    )
    model = BioClipModel(
        species_tokens_path=Path(SPECIES_TOKENS),
        species_names_path=Path(SPECIES_NAMES),
        model_name=BIO_MODEL_NAME,
        model_checkpoint_path=BIO_MODEL_CHECKPOINT_PATH,
        allow_remote_model=BIO_ALLOW_REMOTE_MODEL,
        use_half=USE_HALF,
        text_batch_size=TEXT_BATCH_SIZE,
        image_batch_size=IMAGE_BATCH_SIZE,
    )
    _log_stage("BioClipModel init", model_init_started)
    _log_stage("container startup init block", boot_started)
except FileNotFoundError as e:
    # warn and create a stub object with minimal API so the service
    # can start (analysis endpoints will return empty results).
    logger.warning("BioClip tokens not found: %s; starting stub model", e)

    class _Stub:
        def analyze_image_blobs(self, blobs, threshold=0.05):
            return [(None, 0.0) for _ in blobs]
    model = _Stub()
except Exception as e:
    logger.exception("BioClip initialization failed")
    raise

@app.route("/analyze_images", methods=["POST"])
def analyze_images():
    payload = request.get_json(force=True)
    enc_images = payload.get("images", [])
    blobs = [base64.b64decode(x) for x in enc_images]
    results = model.analyze_image_blobs(blobs, threshold=0.05)
    return jsonify({"results": results})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info("Starting Flask server on 0.0.0.0:%d", port)
    # threaded=True lets health probes be answered while a long inference
    # request is in flight (Flask dev server is single-threaded by default).
    app.run(host="0.0.0.0", port=port, threaded=True)
