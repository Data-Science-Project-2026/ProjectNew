# Singularity build & run

This document shows example `singularity` commands for the project containers and a simple Slurm orchestration example.

There are ready made [scripts](../examples/scripts/README.md) to run the models in the University of Helsinki HPC environment.

No-install policy for the target HPC environment:
- Use prebuilt `.sif` images
- Load Python with `module load python`
- Use `singularity` runtime commands only

Build images (outside HPC compute nodes) — on a machine with Singularity privileges:

```bash
cd /path/to/repo
singularity build src/models/BioClip-Container/BioClip.sif src/models/BioClip-Container/Singularity.def
singularity build src/models/Bert-Container/Bert.sif src/models/Bert-Container/Singularity.def
singularity build src/models/Qwen-Container/Qwen.sif src/models/Qwen-Container/Singularity.def
singularity build src/pipeline/Orchestrator-Container/Orchestrator.sif src/pipeline/Orchestrator-Container/Singularity.def
```

Run a single container (GPU-aware):

```bash
# Bind project directory and data, run Bioclip service in foreground
singularity exec --nv --bind $PWD:/app --pwd /app src/models/BioClip-Container/BioClip.sif python /app/src/models/BioClip-Container/app.py
# then test
curl --noproxy 127.0.0.1 -v http://127.0.0.1:5000/health
```

Run as background processes (simple approach) — all on a single allocated node:

```bash
# start three services in background (adjust binds and --nv as needed)
singularity exec --nv --bind $PWD:/app --pwd /app src/models/BioClip-Container/BioClip.sif bash -c "PORT=5000 python /app/src/models/BioClip-Container/app.py" &
singularity exec --bind $PWD:/app --pwd /app src/models/Bert-Container/Bert.sif bash -c "PORT=5001 python /app/src/models/Bert-Container/app.py" &
singularity exec --bind $PWD:/app --pwd /app src/models/Qwen-Container/Qwen.sif bash -c "PORT=5002 python /app/src/models/Qwen-Container/app.py" &

# wait a few seconds then verify
sleep 3
curl --noproxy 127.0.0.1 -v http://127.0.0.1:5000/health
curl --noproxy 127.0.0.1 -v http://127.0.0.1:5001/health
curl --noproxy 127.0.0.1 -v http://127.0.0.1:5002/health
```

Run with `singularity instance` (optional) — start instance then exec into it:

```bash
singularity instance start --nv --bind $PWD:/app src/models/BioClip-Container/BioClip.sif bioclip
# run health check via exec
singularity exec --no-home instance://bioclip curl --noproxy 127.0.0.1 -v http://127.0.0.1:5000/health
# stop instance
singularity instance stop bioclip
```

Slurm example: start services on one node and run the orchestrator using localhost URLs.
Save this as `run_pipeline_on_node.sh` and submit with `srun --nodes=1 --ntasks=1 --time=01:00:00 bash run_pipeline_on_node.sh` or inside an interactive allocation.

```bash
#!/bin/bash
set -euo pipefail
# ensure NO_PROXY for localhost
export NO_PROXY=127.0.0.1,localhost
export no_proxy=127.0.0.1,localhost

# Working dir
REPO_DIR=$PWD

# Paths to SIF images (assumes built earlier)
BIO_SIF=${REPO_DIR}/src/models/BioClip-Container/BioClip.sif
BERT_SIF=${REPO_DIR}/src/models/Bert-Container/Bert.sif
QWEN_SIF=${REPO_DIR}/src/models/Qwen-Container/Qwen.sif
ORCH_SIF=${REPO_DIR}/src/pipeline/Orchestrator-Container/Orchestrator.sif

# Start services (background)
singularity exec --nv --bind ${REPO_DIR}:/app --pwd /app ${BIO_SIF} bash -c "PORT=5000 python /app/src/models/BioClip-Container/app.py" &
BIO_PID=$!
singularity exec --nv --bind ${REPO_DIR}:/app --pwd /app ${BERT_SIF} bash -c "PORT=5001 python /app/src/models/Bert-Container/app.py" &
BERT_PID=$!
singularity exec --bind ${REPO_DIR}:/app --pwd /app ${QWEN_SIF} bash -c "PORT=5002 python /app/src/models/Qwen-Container/app.py" &
QWEN_PID=$!

# Give services time to start
sleep 5

# Sanity checks
curl --noproxy 127.0.0.1 -sS http://127.0.0.1:5000/health
curl --noproxy 127.0.0.1 -sS http://127.0.0.1:5001/health
curl --noproxy 127.0.0.1 -sS http://127.0.0.1:5002/health

# Run orchestrator upload first, then analysis, pointing to local services
singularity exec --bind ${REPO_DIR}:/app --pwd /app ${ORCH_SIF} python -m pipeline.orchestrator \
    --db-dsn "postgresql://user:pass@db:5432/dbname" \
    upload --csv-folder /input/36Chengdu --image-folder /input/36Chengdu --city Chengdu

singularity exec --bind ${REPO_DIR}:/app --pwd /app ${ORCH_SIF} python -m pipeline.orchestrator \
    --db-dsn "postgresql://user:pass@db:5432/dbname" \
    --bio-service-url "http://127.0.0.1:5000" \
    --bert-service-url "http://127.0.0.1:5001" \
    --qwen-service-url "http://127.0.0.1:5002" \
    analyze --batch-size 1000 --workers 1

# tear down background services
kill ${BIO_PID} ${BERT_PID} ${QWEN_PID} || true
wait || true
```
