import os
import base64
from flask import Flask, request, jsonify

# ensure that the parent package is on the path; when building the Docker
# image we will copy the entire workspace and set PYTHONPATH accordingly.

from models.BioClip.model import BioClipModel

app = Flask(__name__)

# configuration from environment variables
SPECIES_TOKENS = os.environ.get("SPECIES_TOKENS_PATH", "src/models/BioClip/species_tokens_latin.pt")
SPECIES_NAMES = os.environ.get("SPECIES_NAMES_PATH", "src/models/BioClip/species_names_latin.txt")
USE_HALF = bool(os.environ.get("USE_HALF", "False").lower() in ("1", "true"))
TEXT_BATCH_SIZE = int(os.environ.get("TEXT_BATCH_SIZE", 4048))

# initialize the BioClip model; failure to load the token files
# should not crash the entire container during development.  we
# catch the FileNotFoundError and fall back to a dummy instance.
try:
    model = BioClipModel(
        species_tokens_path=SPECIES_TOKENS,
        species_names_path=SPECIES_NAMES,
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
