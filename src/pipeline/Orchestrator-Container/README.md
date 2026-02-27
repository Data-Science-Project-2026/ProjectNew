# Orchestrator Container

This Docker image packages the pipeline orchestrator as a command‑line
service.  It bundles the whole repository so the orchestrator code can
import the models and database helpers directly.

## Build

```sh
cd src/pipeline/Orchestrator-Container
docker build -t pipeline-orchestrator .
```

## Run

The container supports the same CLI options as the standalone script; for
example, to ingest CSVs and images you might run:

```sh
docker run --rm -v /data:/data pipeline-orchestrator upload-posts \
    --city-folder /mnt/f/data/6Shenzhen \
    --db-dsn "dbname=mydb" \
    --bio-service-url http://bio:5000 \
    --sentiment-service-url http://bert:5000 \
    --qwen-service-url http://qwen:5000
```

When running the container, mount your data via a volume and set any needed
environment variables (e.g. `PIPELINE_DATABASE_DSN`).
