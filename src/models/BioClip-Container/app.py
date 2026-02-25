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

model = BioClipModel(
    species_tokens_path=SPECIES_TOKENS,
    species_names_path=SPECIES_NAMES,
    use_half=USE_HALF,
    text_batch_size=TEXT_BATCH_SIZE,
)

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
