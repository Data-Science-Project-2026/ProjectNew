#!/bin/bash
#SBATCH --job-name=bioclip_analyze
#SBATCH -o <path>/logs/dsp2026-%J.txt
#SBATCH -p gpu
#SBATCH --cpus-per-gpu=8
#SBATCH -G 1
#SBATCH --constraint=v100
#SBATCH --mem-per-cpu=4G
#SBATCH --time=24:00:00
#SBATCH --mail-type=END
#SBATCH --mail-user=<email>

set -euxo pipefail

echo "Running in node: $(hostname)"
echo "Running in: $(pwd)"

module load Python cuDNN
source ../venv/bin/activate

DATA=/home/group/grp-dsp2026-hpc-group5/ProjectNew
USER=pehuvio

PGDATA=/home/group/grp-dsp2026-hpc-group5/ProjectNew/pgdata
SOCKETDIR=/home/group/grp-dsp2026-hpc-group5/ProjectNew/pgsocket
LOGDIR=/home/group/grp-dsp2026-hpc-group5/ProjectNew/logs/bioclip
BIOCLIP_LOG="$LOGDIR/bioclip-service.log"
ORCH_LOG="$LOGDIR/bioclip-orchestrator.log"

mkdir -p "$PGDATA"
mkdir -p "$SOCKETDIR"
mkdir -p "$LOGDIR"

echo "PGDATA: $PGDATA"
echo "SOCKETDIR: $SOCKETDIR"
echo "BIOCLIP_LOG: $BIOCLIP_LOG"
echo "ORCH_LOG: $ORCH_LOG"

echo "Starting Postgres..."

singularity exec \
  --bind "$PGDATA:/data" \
  --bind "$SOCKETDIR:/var/run/postgresql" \
  postgres.sif \
  postgres -D /data -h 127.0.0.1 -p 5432 > "$LOGDIR/postgres.log" 2>&1 &

PG_PID=$!

echo "Postgres PID: $PG_PID"

echo "Waiting for Postgres..."

POSTGRES_READY=false

for i in {1..90}; do
  if singularity exec \
      --bind "$DATA:/data" \
      --bind "$SOCKETDIR:/var/run/postgresql" \
      postgres.sif \
      pg_isready -h 127.0.0.1 -p 5432
  then
    echo "Postgres is ready"
    POSTGRES_READY=true
    break
  fi
  echo "Waiting for Postgres ($i)..."
  sleep 2
done

if [ "$POSTGRES_READY" != true ]; then
  echo "ERROR: Postgres did not start"
  echo "--- Postgres log ---"
  tail -100 "$LOGDIR/postgres.log"
  kill $PG_PID 2>/dev/null
  exit 1
fi

echo "Postgres running"
echo "Socket: $SOCKETDIR"

echo "HOST=$(hostname)"
ss -ltnp | grep 5432 || echo "NO TCP LISTEN"
singularity exec postgres.sif pg_isready -h 127.0.0.1 -p 5432 -d postgres


echo "Starting BioClip..."

singularity exec --nv \
  bioclip-service.sif \
  python /app/src/models/BioClip-Container/app.py >>"$BIOCLIP_LOG" 2>&1 &

BIO_PID=$!

sleep 25

echo "=== BIOCLIP PROCESS ==="
ps -fp $BIO_PID

echo "=== CHILDREN ==="
pgrep -af python || true
pgrep -af uvicorn || true
pgrep -af gunicorn || true

echo "=== PORTS ==="
ss -ltnp | grep 5000 || echo "Port 5000 not listening"

BIOCLIP_READY=false

echo "Waiting for Bioclip..." | tee -a "$BIOCLIP_LOG"

for i in {1..120}; do
  if curl -s http://127.0.0.1:5000/health > /dev/null; then
    echo "BioClip is up" | tee -a "$BIOCLIP_LOG"
    BIOCLIP_READY=true
    break
  else
    echo "Bioclip health check attempt $i failed at $(date)" | tee -a "$BIOCLIP_LOG"
    curl -s -m 5 http://127.0.0.1:5000/health 2>&1 | tail -n 10 | sed 's/^/    /' | tee -a "$BIOCLIP_LOG"
  fi
  sleep 5
done

if [ "$BIOCLIP_READY" != true ]; then
  echo "ERROR: Bioclip did not become healthy in time" | tee -a "$BIOCLIP_LOG"
  echo "--- Bioclip process status ---" | tee -a "$BIOCLIP_LOG"
  if ps -p $BIO_PID > /dev/null 2>&1; then
    ps -fp $BIO_PID | tee -a "$BIOCLIP_LOG"
  else
    echo "Bioclip process $BIO_PID is not running" | tee -a "$BIOCLIP_LOG"
  fi
  echo "--- Last 100 lines of $BIOCLIP_LOG ---" | tee -a "$BIOCLIP_LOG"
  tail -n 100 "$BIOCLIP_LOG" | tee -a "$BIOCLIP_LOG"
  echo "--- End of log ---" | tee -a "$BIOCLIP_LOG"
  echo "--- Last 100 lines of $ORCH_LOG ---"
  tail -n 100 "$ORCH_LOG" || true
  kill $BIO_PID || true
  kill $PG_PID || true
  exit 1
fi

sleep 10

echo "Running orchestrator..."
echo "Writing orchestrator log to $ORCH_LOG"
echo "Starting orchestrator" | tee -a "$ORCH_LOG"

singularity exec \
  --bind /home/group/grp-dsp2026-hpc-group5:/data \
  --bind /home/group/grp-dsp2026-hpc-group5/input:/input \
  --bind "$SOCKETDIR:/var/run/postgresql" \
  orchestrator.sif \
  python -m pipeline.orchestrator \
  --db-dsn postgresql://$USER@127.0.0.1:5432/postgres \
  --bio-service-url http://127.0.0.1:5000 \
  --skip-bert \
  --skip-qwen \
  analyze --batch-size 64 > "$ORCH_LOG" 2>&1


echo "Done. Cleaning up..."

kill $BIO_PID
kill $PG_PID
