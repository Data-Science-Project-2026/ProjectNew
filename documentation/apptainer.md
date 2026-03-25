Apptainer / Singularity build & run

This document shows example `apptainer` (Singularity) build and run commands for the project containers and a simple Slurm orchestration example.

Build images (local root) — on a machine with `apptainer` and root privileges:

```bash
cd /path/to/repo
apptainer build src/models/BioClip-Container/BioClip.sif src/models/BioClip-Container/Singularity.def
apptainer build src/models/Bert-Container/Bert.sif src/models/Bert-Container/Singularity.def
apptainer build src/models/Qwen-Container/Qwen.sif src/models/Qwen-Container/Singularity.def
apptainer build src/pipeline/Orchestrator-Container/Orchestrator.sif src/pipeline/Orchestrator-Container/Singularity.def
```

Build images (non-root / remote builder):

```bash
apptainer build --remote src/models/BioClip-Container/BioClip.sif src/models/BioClip-Container/Singularity.def
# repeat for other .def files
```

Run a single container (GPU-aware):

```bash
# Bind project directory and data, run Bioclip service in foreground
apptainer exec --nv --bind $PWD:/app --pwd /app src/models/BioClip-Container/BioClip.sif python /app/src/models/BioClip-Container/app.py
# then test
curl --noproxy 127.0.0.1 -v http://127.0.0.1:5000/health
```

Run as background processes (simple approach) — all on a single allocated node:

```bash
# start three services in background (adjust binds and --nv as needed)
apptainer exec --nv --bind $PWD:/app --pwd /app src/models/BioClip-Container/BioClip.sif bash -c "PORT=5000 python /app/src/models/BioClip-Container/app.py" &
apptainer exec --nv --bind $PWD:/app --pwd /app src/models/Bert-Container/Bert.sif bash -c "PORT=5001 python /app/src/models/Bert-Container/app.py" &
apptainer exec --bind $PWD:/app --pwd /app src/models/Qwen-Container/Qwen.sif bash -c "PORT=5002 python /app/src/models/Qwen-Container/app.py" &

# wait a few seconds then verify
sleep 3
curl --noproxy 127.0.0.1 -v http://127.0.0.1:5000/health
curl --noproxy 127.0.0.1 -v http://127.0.0.1:5001/health
curl --noproxy 127.0.0.1 -v http://127.0.0.1:5002/health
```

Run with `apptainer instance` (optional) — start instance then exec into it:

```bash
apptainer instance start --nv --bind $PWD:/app src/models/BioClip-Container/BioClip.sif bioclip
# run health check via exec
apptainer exec --no-home instance://bioclip curl --noproxy 127.0.0.1 -v http://127.0.0.1:5000/health
# stop instance
apptainer instance stop bioclip
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
apptainer exec --nv --bind ${REPO_DIR}:/app --pwd /app ${BIO_SIF} bash -c "PORT=5000 python /app/src/models/BioClip-Container/app.py" &
BIO_PID=$!
apptainer exec --nv --bind ${REPO_DIR}:/app --pwd /app ${BERT_SIF} bash -c "PORT=5001 python /app/src/models/Bert-Container/app.py" &
BERT_PID=$!
apptainer exec --bind ${REPO_DIR}:/app --pwd /app ${QWEN_SIF} bash -c "PORT=5002 python /app/src/models/Qwen-Container/app.py" &
QWEN_PID=$!

# Give services time to start
sleep 5

# Sanity checks
curl --noproxy 127.0.0.1 -sS http://127.0.0.1:5000/health
curl --noproxy 127.0.0.1 -sS http://127.0.0.1:5001/health
curl --noproxy 127.0.0.1 -sS http://127.0.0.1:5002/health

# Run orchestrator pointing to local services
apptainer exec --bind ${REPO_DIR}:/app --pwd /app ${ORCH_SIF} python -m pipeline.orchestrator \
    --dsn "postgresql://user:pass@db:5432/dbname" \
    --bio-service-url "http://127.0.0.1:5000" \
    --bert-service-url "http://127.0.0.1:5001" \
    --qwen-service-url "http://127.0.0.1:5002"

# tear down background services
kill ${BIO_PID} ${BERT_PID} ${QWEN_PID} || true
wait || true
```

Notes & tips

- Proxy/no_proxy: set `NO_PROXY`/`no_proxy` for `127.0.0.1,localhost` to ensure `curl` and Python `requests` do not use the cluster proxy for intra-node calls.
- Building images requiring GPU libs: base images using `nvidia/cuda` may be large — prefer building on a host with the same CUDA stack or use `docker://` bootstrap so remote builder pulls the base image.
- If you cannot build SIF locally and `apptainer build --remote` is not allowed, ask admins to provide the built SIF files or enable remote builds.
- Port binding: Apptainer does not map host ports like Docker; run all services on the same node and use `127.0.0.1:<port>` to reach them from the orchestrator when they share the job allocation.
- If Slurm isolates network namespaces between tasks, run all services and the orchestrator inside the same allocation/process (as above) or use a single job script to start them.

Further help

If you'd like, I can:
- generate a `run_pipeline_on_node.sh` file in the repo (ready-to-run), or
- create CI examples that use `apptainer build --remote` and upload SIF artifacts.

Helper scripts

We provide several helper scripts under `examples/scripts/` to simplify SIF builds and runner setup:

- `build_sifs_local.sh` — Build all images locally (root required). Usage:

```bash
sudo bash examples/scripts/build_sifs_local.sh
```

- `build_sifs_remote.sh` — Use `apptainer build --remote` to build SIFs without root.

```bash
bash examples/scripts/build_sifs_remote.sh
```

- `install_apptainer_runner.sh` — (Optional) Install Apptainer on a self-hosted Ubuntu runner. Run as root on the runner machine.

```bash
sudo bash examples/scripts/install_apptainer_runner.sh
```

These scripts are small wrappers around the commands shown above and check for missing files or prerequisites; inspect them before running in your environment.
