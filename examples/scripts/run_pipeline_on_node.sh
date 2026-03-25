#!/usr/bin/env bash
set -euo pipefail

# Run the pipeline on a single allocated node using Apptainer instances.
# Usage (inside an allocation):
#   bash examples/scripts/run_pipeline_on_node.sh
# or submit with srun/sbatch as a single-node job.

export NO_PROXY=127.0.0.1,localhost
export no_proxy=127.0.0.1,localhost

REPO_DIR=${REPO_DIR:-$PWD}

# Paths to SIF images (must be built beforehand)
BIO_SIF=${REPO_DIR}/src/models/BioClip-Container/BioClip.sif
BERT_SIF=${REPO_DIR}/src/models/Bert-Container/Bert.sif
QWEN_SIF=${REPO_DIR}/src/models/Qwen-Container/Qwen.sif
ORCH_SIF=${REPO_DIR}/src/pipeline/Orchestrator-Container/Orchestrator.sif

# Ports used by services
BIO_PORT=${BIO_PORT:-5000}
BERT_PORT=${BERT_PORT:-5001}
QWEN_PORT=${QWEN_PORT:-5002}

# Ensure SIFs exist
for f in "$BIO_SIF" "$BERT_SIF" "$QWEN_SIF" "$ORCH_SIF"; do
  if [ ! -f "$f" ]; then
    echo "Missing SIF: $f"
    echo "Build images first (see documentation/apptainer.md)."
    exit 1
  fi
done

# Start instances
echo "Starting BioClip instance..."
apptainer instance start --nv --bind "${REPO_DIR}:/app" --pwd /app "$BIO_SIF" bioclip || { echo "failed to start bioclip"; exit 1; }

echo "Starting Bert instance..."
apptainer instance start --nv --bind "${REPO_DIR}:/app" --pwd /app "$BERT_SIF" bert || { echo "failed to start bert"; exit 1; }

echo "Starting Qwen instance..."
apptainer instance start --bind "${REPO_DIR}:/app" --pwd /app "$QWEN_SIF" qwen || { echo "failed to start qwen"; exit 1; }

# Give services time to initialize
sleep 5

# Sanity checks
echo "Health checks:"
apptainer exec --no-home instance://bioclip curl --noproxy 127.0.0.1 -sS "http://127.0.0.1:${BIO_PORT}/health" || { echo "bioclip health failed"; }
apptainer exec --no-home instance://bert curl --noproxy 127.0.0.1 -sS "http://127.0.0.1:${BERT_PORT}/health" || { echo "bert health failed"; }
apptainer exec --no-home instance://qwen curl --noproxy 127.0.0.1 -sS "http://127.0.0.1:${QWEN_PORT}/health" || { echo "qwen health failed"; }

# Run orchestrator pointing at local services
echo "Running orchestrator against local services..."
apptainer exec --bind "${REPO_DIR}:/app" --pwd /app "$ORCH_SIF" python -m pipeline.orchestrator \
  --bio-service-url "http://127.0.0.1:${BIO_PORT}" \
  --bert-service-url "http://127.0.0.1:${BERT_PORT}" \
  --qwen-service-url "http://127.0.0.1:${QWEN_PORT}"

# Tear down instances
echo "Stopping instances..."
apptainer instance stop bioclip || true
apptainer instance stop bert || true
apptainer instance stop qwen || true

echo "Done."
