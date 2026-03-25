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
imports CSVs, ingests raw image files (copying them into a managed
`image_root` directory) and then runs three kinds of models (BioClip, sentiment/BERT and Qwen) and writes results to a PostgreSQL database. For production provide a Postgres DSN via `--db-dsn` or the `PIPELINE_DATABASE_DSN` environment variable; SQLite is supported only in tests and import utilities.

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

Note: the compose file shipped with the repo exposes model services on
ports 5000–5002 and Postgres on 5432. The orchestrator service instances
mount `./data/split_*` so each orchestrator can work on a separate data
shard.

### Uploading CSVs or Images into the Orchestrator

The orchestrator expects input under `/data` inside the container. The
compose file mounts host `./data/split_1` (and `split_2`) into the
`orchestrator-1` service so a convenient test is to place files in
`data/split_1` on the host and run the one‑off orchestrator container.

Example (this repository used `data/split_1` during testing):

```powershell
# ingest images from the mounted folder into Postgres
docker compose run --rm orchestrator-1 \
  --db-dsn "dbname=mydb user=myuser password=mypass host=postgres port=5432" \
  upload-images --folders /data --image-root /data/images

# run full analysis (BioClip, Bert, Qwen via services)
docker compose run --rm orchestrator-1 \
  --db-dsn "dbname=mydb user=myuser password=mypass host=postgres port=5432" \
  --bio-service-url http://bioclip:5000 \
  --bert-service-url http://bert:5000 \
  --qwen-service-url http://qwen:5000 \
  analyze --batch-size 10 --workers 1
```

Notes:
- If you have CSVs, use `upload-posts --city-folder /data` (the command
  looks for CSVs and associated park image folders inside the provided
  folder). The orchestrator will write records to `posts` and `images`.
- `upload-images` copies each image into `image_root` named by the DB id
  and persists the original path into the DB so analyzers can access the
  original file (mounted path) or the copied storage path.
- To avoid loading large local models during quick tests, use
  `--skip-bio` and/or `--skip-bert` and point at running service URLs.

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

[Species indentification documentation](./documentation/species_identification.md)

[Sentiment analysis documentation](./documentation/sentiment_analysis.md)

[Human activity recognition documentation](./documentation/human_activity_recognition.md)

## HPC / Apptainer

If you run this project on an HPC cluster where Docker is unavailable, we provide Singularity/Apptainer support and example job scripts. See [documentation/apptainer.md](./documentation/apptainer.md) for build and run instructions and the `examples/scripts/run_pipeline_on_node.sh` helper to start model service instances on a single allocated node.

Key notes:

- Build SIF images locally or with the remote builder: `apptainer build --remote <image>.sif <Singularity.def>`
- Use `apptainer instance start|exec` to run services and reach them via `http://127.0.0.1:<port>` from the orchestrator.
- Ensure `NO_PROXY`/`no_proxy` includes `127.0.0.1,localhost` so intra-node requests bypass cluster proxies.

## License

This project was developed for a Data Science course (University of
Helsinki, 2026).

## Authors

Group 5 - Data Science Project 2026
