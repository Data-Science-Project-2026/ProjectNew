# Orchestrator Container

This Docker image packages the pipeline orchestrator as a command‑line
service.  It bundles the whole repository so the orchestrator code can
import the models and database helpers directly.

## Build

```sh
cd /path/to/repo
docker build -f src/pipeline/Orchestrator-Container/Dockerfile -t pipeline-orchestrator .
```

The Dockerfile copies `src/` from the repository root, so the build context
must be the repository root rather than `src/pipeline/Orchestrator-Container`.

## Run

The container supports the same CLI options as the standalone script; for
example, to ingest CSVs and images you might run:

```sh
docker run --rm -v /data:/data pipeline-orchestrator \
    --db-dsn "dbname=mydb" \
    upload --csv-folder /data/csvs --image-folder /data/images \
    --image-folders /data/extra-images

# if the mounted folder name is generic (for example /input), pass the city explicitly
docker run --rm -v /input:/input pipeline-orchestrator \
    --db-dsn "dbname=mydb" \
    upload --csv-folder /input/36Chengdu --image-folder /input/36Chengdu --city Chengdu

docker run --rm -v /data:/data pipeline-orchestrator \
    --db-dsn "dbname=mydb" \
    analyze \
    --bio-service-url http://bio:5000 \
    --bert-service-url http://bert:5000 \
    --qwen-service-url http://qwen:5000
```

When running the container, mount your data via a volume and set any needed
environment variables (e.g. `PIPELINE_DATABASE_DSN`).
