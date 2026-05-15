#!/bin/bash
#SBATCH --job-name=qwen_analyze
#SBATCH -o <path>/logs/dsp2026-%J.txt
#SBATCH -p gpu
#SBATCH --cpus-per-gpu=6
#SBATCH -G 1
#SBATCH --constraint=a100
#SBATCH --mem-per-cpu=24G
#SBATCH --mail-type=END
#SBATCH --mail-user=<email>
#SBATCH --nodelist=<node>
echo "Running in node: $(hostname)"
echo "Running in: $(pwd)"

DATA=<path>/ProjectNew
PGDATA=<path>/ProjectNew/pgdata
SOCKETDIR=<path>/ProjectNew/pgsocket
USER=<username>

mkdir -p "$PGDATA"
mkdir -p "$SOCKETDIR"

echo "Starting vllm..."

singularity exec --nv qwen-service.sif \
python -m vllm.entrypoints.openai.api_server \
--model /app/models/Qwen3.5-4B \
--host 0.0.0.0 \
--port 8000 \
--max-model-len 4096 \
--gpu-memory-utilization 0.9 \
--max-num-seqs 16 &

VLLM_PID=$!

echo "Waiting for vllm..."

for i in {1..30}; do
  if curl http://localhost:8000/v1/models > /dev/null; then
    echo "vLLM is up"
    break
  fi
  sleep 2
done

echo "Starting Qwen..."

singularity exec --nv qwen-service.sif \
python /app/src/models/Qwen-Container/app.py &

QWEN_PID=$!

echo "Waiting for Qwen..."

for i in {1..30}; do
  if curl -s http://127.0.0.1:5000/health > /dev/null; then
    echo "Qwen is up"
    break
  fi
  sleep 2
done

echo "Running orchestrator..."

singularity exec \
--bind $DATA:/data \
--bind "$SOCKETDIR:/var/run/postgresql" \
orchestrator.sif \
python -m pipeline.orchestrator \
--db-dsn postgresql://127.0.0.1:5432/postgres \
--qwen-service-url http://127.0.0.1:5000 \
--skip-bio \
--skip-bert \
analyze --batch-size 8


echo "Done. Cleaning up..."

kill $QWEN_PID
kill $VLLM_PID
