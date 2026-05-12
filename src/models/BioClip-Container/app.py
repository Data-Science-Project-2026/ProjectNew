import os
import base64
import subprocess
import sys
from pathlib import Path
from flask import Flask, request, jsonify

# ensure that the parent package is on the path; when building the Docker
# image we will copy the entire workspace and set PYTHONPATH accordingly.

from models.BioClip.model import BioClipModel

app = Flask(__name__)

SRC_ROOT = Path(__file__).resolve().parents[2]
BIOCLIP_DIR = SRC_ROOT / "models" / "BioClip"
TOKENIZE_SCRIPT = BIOCLIP_DIR / "tokenize_excel_species.py"

@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

# configuration from environment variables
SPECIES_TOKENS = os.environ.get("SPECIES_TOKENS_PATH", str(BIOCLIP_DIR / "species_tokens_latin.pt"))
SPECIES_NAMES = os.environ.get("SPECIES_NAMES_PATH", str(BIOCLIP_DIR / "species_names_latin.txt"))
SPECIES_SOURCE_XLSX = os.environ.get("SPECIES_SOURCE_XLSX", str(BIOCLIP_DIR / "Species_China.xlsx"))
USE_HALF = bool(os.environ.get("USE_HALF", "False").lower() in ("1", "true"))
TEXT_BATCH_SIZE = int(os.environ.get("TEXT_BATCH_SIZE", 4048))


def _ensure_species_assets() -> None:
    tokens_path = Path(SPECIES_TOKENS)
    names_path = Path(SPECIES_NAMES)
    xlsx_path = Path(SPECIES_SOURCE_XLSX)

    if tokens_path.exists() and names_path.exists():
        return

    if not xlsx_path.exists():
        raise FileNotFoundError(
            f"Missing species source file: {xlsx_path}. Cannot generate BioClip token assets."
        )

    tokens_path.parent.mkdir(parents=True, exist_ok=True)
    names_path.parent.mkdir(parents=True, exist_ok=True)

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

# initialize the BioClip model; failure to load the token files
# should not crash the entire container during development.  we
# catch the FileNotFoundError and fall back to a dummy instance.
try:
    _ensure_species_assets()
    model = BioClipModel(
        species_tokens_path=Path(SPECIES_TOKENS),
        species_names_path=Path(SPECIES_NAMES),
        use_half=USE_HALF,
        text_batch_size=TEXT_BATCH_SIZE,
    )
except FileNotFoundError as e:
    # warn and create a stub object with minimal API so the service
    # can start (analysis endpoints will return empty results).
    import logging
    logging.warning("BioClip tokens not found: %s; starting stub model", e)

    class _Stub:
        def analyze_image_blobs(self, blobs, threshold=0.05):
            return [(None, 0.0) for _ in blobs]
    model = _Stub()

@app.route("/analyze_images", methods=["POST"])
def analyze_images():
    payload = request.get_json(force=True)
    enc_images = payload.get("images", [])
    blobs = [base64.b64decode(x) for x in enc_images]
    results = model.analyze_image_blobs(blobs, threshold=0.05)
    return jsonify({"results": results})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
