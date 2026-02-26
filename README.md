# Data Science Project

Multimodal analysis of human-nature interactions based on large social media dataset. The purpose of the project is to visualize information about urban nature in social media posts. Posts can contain images or text. Sentiment analysis is performed on text-based posts. Images are analyzed to determine whether they are people, plants, or animals. If there are humans in the pictures, then human activity recognition is performed. In case of animals or plants fine-grained species identification is performed.

## Dataset

**Source**: Crowdsourced data from Ctrip.com (similar to TripAdvisor)

**Scope**: 720 representative urban parks in 36 cities in China

**Volume**: Around 853,977 pieces of social media texts and 985,025 social media images in total

**Metadata**: Geotags and timestamps

[Database documentation](./documentation/database.md)

## Dashboard

Free open source dashboard tool [Metabase](https://www.metabase.com/) is used for this project.

[Dashboard documentation](./documentation/dashboard.md)

## Pipeline & Deployment

The core workflow is orchestrated by `src/pipeline/orchestrator.py`.  It
imports CSVs, ingests raw image files (copying them into a managed
``image_root`` directory) and then runs three kinds of models
(BioClip, sentiment/BERT and Qwen) and writes results to a PostgreSQL
database.  The database never stores the original file paths or blobs –
only numeric ids and hashes – keeping the PG instance lightweight.  For
production you should provide a Postgres DSN via `--db-dsn` or the
`PIPELINE_DATABASE_DSN` environment variable; SQLite is supported only in
tests and import utilities.

[Pipeline documentation](./documentation/pipeline.md)

### Running with Docker Compose

A `docker-compose.yml` file is provided at the repo root that can build and
orchestrate the orchestrator and model containers together (Postgres +
services).  By default the orchestrator service is configured to run a
single ingestion command and then exit, so it is _not_ a long‑running
process.  You can still upload data by starting a fresh container (see
below) or by overriding the command to keep it alive.  Typical commands:

```sh
# build images and start everything in the background
docker-compose up -d --build

# view logs for all services
docker-compose logs -f

# stop the running containers without removing them
docker-compose stop

# remove stopped containers, networks, and volumes defined in the file
docker-compose down
```

If you only want to remove containers but keep the volumes, omit `--volumes`;
use `docker-compose down --volumes --rmi all` to tidy up completely.  

**Tip:** when you’ve updated the code and need a fresh image, run the
`down --volumes --rmi all` command to purge the existing containers and then
start again with `up --build`; this ensures you’re not running stale code.

You can also rebuild a single service without touching the others. For
example, if you've modified `src/pipeline/orchestrator.py` or any other
code and need those changes in the container, rebuild the orchestrator
image:

```sh
# rebuild only orchestrator with updated code
docker-compose build orchestrator
```

and then run it again (see the ingest/upload examples below).  The
same pattern works for `bioclip`, `bert`, or `qwen`.

For example, to recreate only the BioClip container:

```sh
# stop the single container
docker-compose stop bioclip
# remove its image so the next `up` builds from scratch
docker-compose rm -f bioclip
# rebuild and start it
docker-compose up -d --build bioclip
```

Replace `bioclip` with `bert`, `qwen`, or `orchestrator` as needed.

### Uploading CSVs or Images into the Orchestrator (while containers are running)

When using `docker-compose` the repository `data/` directory is mounted into the
`orchestrator` container at `/data`. Place your input files under that tree so the
running container can access them. Example layout on the host:

```sh
mkdir -p data/csvs data/images
# copy CSV files into data/csvs and any loose images into data/images or another folder
```

Two common ways to trigger ingestion while the containers are running (or even when the orchestrator has already stopped, since a new container will be launched):

- **If the orchestrator is still running** you can exec into it as shown below:

```sh
docker-compose exec orchestrator \
	upload-posts --csv-dir /data/csvs --image-root /data/images

# or to ingest image folders directly
docker-compose exec orchestrator \
	upload-images --folders /data/new_photos --image-root /data/images
```

- More commonly you will use a one‑off container (works even when the service has exited):

```sh
docker-compose run --rm orchestrator \
	upload-posts --csv-dir /data/csvs --image-root /data/images
```

Notes:
- The `--image-root` path should point to a directory writable by the orchestrator (the default used by this repo is `/data/images`).
- CSV rows may include relative image paths; when using `upload-posts` provide `--image-root` so the ingestor can resolve those paths. If you use `upload-images` the ingestor will copy each file into `/data/images` and name it by numeric image id.
- If you only care about a particular model (e.g. Qwen) you can skip others by using the `--skip-bio`/`--skip-bert` flags or by pointing them at a running service instead of loading locally. Example of a Qwen-only upload:

  ```sh
  docker-compose run --rm orchestrator \
      --db-dsn "dbname=mydb user=myuser password=mypass host=postgres port=5432" \
      --qwen-service-url http://qwen:5000 \
      --skip-bio --skip-bert \
      upload-images --folders /data/images --image-root /data/images
  ```

  This prevents the orchestrator from downloading the large BioClip weights when you're just testing the Qwen endpoint.

- On Windows PowerShell use the equivalent `New-Item -ItemType Directory -Path data\csvs,data\images` to create folders.


### Running the integration tests

A pair of pytest tests exercise the orchestrator against the Bioclip and
Qwen containers. They copy three sample images from
`data/images/53深圳市宝安区西乡公园` into a temporary directory, start the
necessary services with `docker-compose`, and then invoke the pipeline
programmatically.

To run them locally (requires Docker & docker-compose):

```sh
# start just the infra; tests will bring the containers up/down themselves
docker-compose up -d postgres bioclip qwen
pytest src/pipeline/tests/test_container_integration.py
```

The tests use the same DSN as the compose file and assume the containers are
reachable on `localhost` ports 5432, 5000 and 5002.

### Containers for models

Each model is available as a standalone Docker service under `src/models`:

* `BioClip-Container` – species identification
* `Bert-Container` – sentiment analysis
* `Qwen-Container` – human activity recognition

Instructions for building and running them are available in each subfolder.
The orchestrator can be pointed at any combination of running services using
the `--bio-service-url`, `--sentiment-service-url` and
`--qwen-service-url` CLI flags, in which case batches are POSTed to the
container and the JSON response is used just as if the local model had been
running.

[Species indentification documentation](./documentation/species_identification.md)

[Sentiment analysis documentation](./documentation/sentiment_analysis.md)

[Human activity recognition documentation](./documentation/human_activity_recognition.md)

## License

This project is for a Data Science course at the University of Helsinki (2026).

## Authors

Group 5 - Data Science Project 2026
