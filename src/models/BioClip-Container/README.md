# BioClip Container

This directory holds a small Flask service that wraps the `BioClipModel`.
It exposes a single endpoint:

* `POST /analyze_images` – payload `{ "images": [base64, ...] }`, returns
  `{ "results": [ [speciesList, confidenceList], ... ] }`.

The container image also includes a standalone batch analyzer; the
implementation lives in `models/BioClip/analyzer.py` and can be invoked
without running the Flask service.  This is useful when you want the
container to process rows directly from a PostgreSQL database instead of
receiving requests from the orchestrator.

To build and run the HTTP service:

```sh
cd src/models/BioClip-Container
docker build -t bioclip-service .
docker run -p 5000:5000 bioclip-service
```

To run the batch analyzer inside the same image:

```sh
# assume images are stored in /data/images on the host
# and the Postgres DSN is available as an environment variable
docker run --rm \
    -e DB_DSN="your_dsn_here" \
    -v /path/to/images:/data/images \
    bioclip-service \
    python -m models.BioClip.analyzer --db-dsn "$DB_DSN" --image-root /data/images
```

Environment variables allow configuration of model paths and options.

## Auto-generation of species token files

On startup, the container now checks whether these files exist:

* `src/models/BioClip/species_names_latin.txt`
* `src/models/BioClip/species_tokens_latin.pt`

If missing, it automatically runs:

```sh
python3 src/models/BioClip/tokenize_excel_species.py \
  src/models/BioClip/Species_China.xlsx \
  src/models/BioClip/species_names_latin.txt \
  src/models/BioClip/species_tokens_latin.pt
```

You can override the source XLSX path with:

* `SPECIES_SOURCE_XLSX` (default: `src/models/BioClip/Species_China.xlsx`)
