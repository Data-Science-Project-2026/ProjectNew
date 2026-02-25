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
imports CSVs, ingests image paths, then runs three kinds of models
(BioClip, sentiment/BERT and Qwen) and writes results to a PostgreSQL
database.  For production you should provide a Postgres DSN via
`--db-dsn` or the `PIPELINE_DATABASE_DSN` environment variable; SQLite is
supported only in tests and import utilities.

[Pipeline documentation](./documentation/pipeline.md)

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
