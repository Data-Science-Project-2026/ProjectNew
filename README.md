# Data Science Project

Multimodal analysis of human–nature interactions built around a PostgreSQL-backed
pipeline. The orchestrator ingests CSVs and/or image folders, stores metadata
in Postgres and dispatches image/text batches to model services (BioClip,
Bert, Qwen). The repository includes container definitions so you can run the
entire pipeline locally with Docker Compose.

## Dataset

Source and example dataset information are described in the `documentation/`
folder. This repository ships tools and models to process CSVs and image
collections; the pipeline writes analytical results into a Postgres database —
see [documentation/database.md](./documentation/database.md) for the schema and
recommended Postgres settings.

## Dashboard

Free open source dashboard tool [Metabase](https://www.metabase.com/) is used for this project.

[Dashboard documentation](./documentation/dashboard.md)

## Pipeline & Deployment

The core workflow is orchestrated by `src/pipeline/orchestrator.py`. It
imports CSVs, ingests raw image files, and then runs three kinds of models
(BioClip, sentiment/BERT and Qwen). Image files are analyzed from their
original paths recorded in the database (files are not copied). By default
results are written to a PostgreSQL
database. For production provide a Postgres DSN via `--db-dsn` or the
`PIPELINE_DATABASE_DSN` environment variable; SQLite is supported only in
tests and import utilities.

Model execution status is tracked per row in Postgres:

- posts: Bert and Qwen status fields
- images: BioClip and Qwen status fields

Each model path transitions through `pending -> processing -> ready` (or
`failed` on error). Stale rows in `processing` for more than 1 hour are
reset back to `pending` before the next claim.

Note: the orchestrator also supports a DB-less JSON output mode via
`--output-json <path>`. When provided the orchestrator will bypass the
database entirely and collect `posts`, `images` and analysis results in an
in-memory store which is written to the given JSON file at the end of the
run. This is useful for quick local inspections or CI runs where Postgres is
not available.

[Pipeline documentation](./documentation/pipeline.md)

### Running with Docker Compose (Postgres first)

This project is Postgres‑first. The recommended flow for local testing is
to use `docker compose` to build and start services. Example commands used
in local development:

```powershell
# build images and start everything in the background
docker compose up -d --build

# watch logs (follow)
docker compose logs -f

# stop containers
docker compose stop

# remove containers, networks and keep volumes:
docker compose down

# remove everything (images + volumes) when you want a fully clean rebuild
docker compose down --volumes --rmi all
```

To rebuild a single image use `docker compose build <service>` and then
restart that service. Example:

```powershell
docker compose build bioclip
docker compose up -d bioclip
```

### Uploading Data into the Orchestrator

The orchestrator loads csv files containing posts and images to database. It checks all
the subfolders.

```powershell
# ingest posts and images in one step
docker compose run --rm orchestrator-1 \
  --db-dsn "dbname=mydb user=myuser password=mypass host=postgres port=5432" \
  upload --csv-folder /data --image-folder /data

# run full analysis (BioClip, Bert, Qwen via services)
docker compose run --rm orchestrator-1 \
  --db-dsn "dbname=mydb user=myuser password=mypass host=postgres port=5432" \
  --bio-service-url http://bioclip:5000 \
  --bert-service-url http://bert:5000 \
  --qwen-service-url http://qwen:5000 \
  analyze --batch-size 10 --workers 1
```

If you want a single step-by-step script for a fresh local run, use:

```powershell
# 1) start required services
docker compose up -d postgres bioclip bert qwen

# 2) import CSV posts and images
docker compose run --rm orchestrator-1 \
  --db-dsn "dbname=mydb user=myuser password=mypass host=postgres port=5432" \
  upload --csv-folder /data --image-folder /data

# 3) run analysis using service containers
docker compose run --rm orchestrator-1 \
  --db-dsn "dbname=mydb user=myuser password=mypass host=postgres port=5432" \
  --bio-service-url http://bioclip:5000 \
  --bert-service-url http://bert:5000 \
  --qwen-service-url http://qwen:5000 \
  analyze --batch-size 10 --workers 1
```

Notes:

- Use `upload` for ingestion. It supports `--csv-folder`, optional
  `--image-folder`, and optional extra `--image-folders` values.
- If the container mount path is generic, such as `/input`, pass `--city`
  explicitly so `posts.city` uses the real city name instead of the mount
  folder.
- The orchestrator stores original image paths in `images.path` and
  analyzers read those original files directly.
- To avoid loading large local models during quick tests, use
  `--skip-bio` and/or `--skip-bert` and point at running service URLs.

To build the standalone orchestrator image directly, run from the repository
root:

```powershell
docker build -f src/pipeline/Orchestrator-Container/Dockerfile -t pipeline-orchestrator .
```

### Running the integration tests

Tests are located under `src/pipeline/tests`. They are designed to run
against the Docker services (the tests will assume the Postgres DSN and
service ports used by the compose file). Example:

```powershell
docker compose up -d postgres bioclip qwen
pytest src/pipeline/tests/test_container_integration.py -q
```

The tests may rely on `OPENAI_API_KEY="EMPTY"` (Qwen stub) for local
CI-friendly runs; the compose file sets that by default so the tests don't
call external LLMs during local development.

### Containers for models

Model containers live under `src/models`:

- `BioClip-Container` – species identification (OpenCLIP + token assets)
- `Bert-Container` – sentiment analysis
- `Qwen-Container` – comment + image text analysis (LLM wrapper)

The orchestrator can dispatch work to any combination of the above via
`--bio-service-url`, `--bert-service-url` and `--qwen-service-url`.

Important runtime notes:

- Qwen local stub: the compose file sets `OPENAI_API_KEY="EMPTY"` and
  `OPENAI_BASE_URL` to a host gateway. When `OPENAI_API_KEY` is empty the
  Qwen service runs in a deterministic *stub* mode that returns well-formed
  JSON for image/comment analysis. This is useful for local, offline tests
  and CI. To use a real LLM backend, set `OPENAI_API_KEY` and point
  `OPENAI_BASE_URL` to a compatible service.

- BioClip GPU memory: on modest GPUs (12GB) the full token set + model can
  cause CUDA OOMs. The compose file supports `USE_HALF=true` and a
  reduced `TEXT_BATCH_SIZE` environment override to run in mixed/half
  precision; this significantly reduces VRAM usage and was used during
  local testing (see `docker-compose.yml`). If you have larger GPUs you
  can omit `USE_HALF` for best accuracy.

- BioClip offline loading: the orchestrator supports loading a local
  OpenCLIP checkpoint file so no Hugging Face access is required at runtime.
  Use (without flag, default path = "src/models/BioClip/open_clip_pytorch_model.bin")

```powershell
python src/pipeline/orchestrator.py \
  --bio-model-checkpoint /path/to/bioclip_checkpoint.pt \
  analyze --batch-size 10 --workers 1
```

[Species indentification documentation](./documentation/species_identification.md)

[Sentiment analysis documentation](./documentation/sentiment_analysis.md)

[Human activity recognition documentation](./documentation/human_activity_recognition.md)

## HPC / Apptainer

If you run this project on an HPC cluster where Docker is unavailable, we provide Singularity support and example job scripts. See [documentation/apptainer.md](./documentation/apptainer.md) for build and run instructions and [example scripts](./examples/scripts/README.md).

Key notes:

- SIF image builds are performed externally (e.g. on an HPC cluster); project
  repository no longer includes automated SIF build workflows or scripts.
- Use `apptainer instance start|exec` to run services and reach them via `http://127.0.0.1:<port>` from the orchestrator.
- Ensure `NO_PROXY`/`no_proxy` includes `127.0.0.1,localhost` so intra-node requests bypass cluster proxies.

## License

This project was developed for a Data Science course (University of
Helsinki, 2026).

## Authors

Group 5 - Data Science Project 2026
