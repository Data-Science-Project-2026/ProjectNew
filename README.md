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
services).  Typical commands:

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
example, to recreate only the BioClip container:

```sh
# stop the single container
docker-compose stop bioclip
# remove its image so the next `up` builds from scratch
docker-compose rm -f bioclip
# rebuild and start it
docker-compose up -d --build bioclip
```

Replace `bioclip` with `bert`, `qwen`, or `orchestrator` as needed.

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
