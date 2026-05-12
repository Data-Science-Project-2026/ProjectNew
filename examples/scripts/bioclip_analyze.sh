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

echo "Running in node: $(hostname)"
echo "Running in: $(pwd)"

module load Python cuDNN
source ../venv/bin/activate

DATA=<path>/ProjectNew
USER=<username>

PGDATA=<path>/ProjectNew/pgdata
SOCKETDIR=<path>/ProjectNew/pgsocket
LOGDIR=<path>/ProjectNew/logs/bioclip
BIOCLIP_PORT=${BIOCLIP_PORT:-5000}
if [ -n "${SLURM_JOB_ID:-}" ]; then
  BIOCLIP_PORT=$((5000 + SLURM_JOB_ID % 1000))
fi
BIOCLIP_LOG="$LOGDIR/bioclip-service.log"
ORCH_LOG="$LOGDIR/bioclip-orchestrator.log"

mkdir -p "$PGDATA"
mkdir -p "$SOCKETDIR"
mkdir -p "$LOGDIR"

echo "PGDATA: $PGDATA"
echo "SOCKETDIR: $SOCKETDIR"
echo "BIOCLIP_PORT: $BIOCLIP_PORT"
echo "BIOCLIP_LOG: $BIOCLIP_LOG"
echo "ORCH_LOG: $ORCH_LOG"

echo "Starting Postgres..."

singularity exec \
--bind "$PGDATA:/data" \
--bind "$SOCKETDIR:/var/run/postgresql" \
postgres.sif \
postgres -D /data -h 127.0.0.1 -p 5432 &

PG_PID=$!

echo "Postgres PID: $PG_PID"

which pg_isready || echo "NO pg_isready in PATH"
singularity exec postgres.sif which pg_isready

for i in {1..30}; do
  singularity exec \
    --bind "$DATA:/data" \
    postgres.sif \
    pg_isready -h 127.0.0.1 -p 5432
  if [ $? -eq 0 ]; then
    echo "Postgres is ready"
    break
  fi
  sleep 2
done

echo "Postgres running"
echo "Socket: $SOCKETDIR"

echo "HOST=$(hostname)"
ss -ltnp | grep 5432 || echo "NO TCP LISTEN"
singularity exec postgres.sif pg_isready -h 127.0.0.1 -p 5432 -d postgres || echo "Postgres readiness check (informational)"


echo "Starting BioClip..."
echo "Writing BioClip service logs to $BIOCLIP_LOG"
echo "Starting BioClip service on port $BIOCLIP_PORT" | tee -a "$BIOCLIP_LOG"

if ss -ltn | grep -q ":$BIOCLIP_PORT "; then
  echo "ERROR: port $BIOCLIP_PORT is already in use, cannot start BioClip" | tee -a "$BIOCLIP_LOG"
  exit 1
fi

BIOCLIP_URL="http://127.0.0.1:$BIOCLIP_PORT"

singularity exec --nv --env PORT="$BIOCLIP_PORT" bioclip-service.sif \
python /app/src/models/BioClip-Container/app.py >>"$BIOCLIP_LOG" 2>&1 &

BIO_PID=$!

BIOCLIP_READY=false

echo "Waiting for BioClip..." | tee -a "$BIOCLIP_LOG"
for i in {1..30}; do
  if curl -s -o /dev/null "$BIOCLIP_URL/health"; then
    echo "BioClip is up" | tee -a "$BIOCLIP_LOG"
    BIOCLIP_READY=true
    break
  else
    echo "BioClip health check attempt $i failed at $(date)" | tee -a "$BIOCLIP_LOG"
    curl -s -m 5 "$BIOCLIP_URL/health" 2>&1 | tail -n 10 | sed 's/^/    /' | tee -a "$BIOCLIP_LOG"
  fi
  sleep 2
done

if [ "$BIOCLIP_READY" != "true" ]; then
  echo "ERROR: BioClip did not become healthy in time" | tee -a "$BIOCLIP_LOG"
  echo "--- BioClip process status ---" | tee -a "$BIOCLIP_LOG"
  if ps -p $BIO_PID > /dev/null 2>&1; then
    ps -fp $BIO_PID | tee -a "$BIOCLIP_LOG"
  else
    echo "BioClip process $BIO_PID is not running" | tee -a "$BIOCLIP_LOG"
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
echo "Writing orchestrator logs to $ORCH_LOG"
echo "Starting orchestrator" | tee -a "$ORCH_LOG"

singularity exec \
--bind <path>/ProjectNew:/data \
--bind <path>/ProjectNew/input:/input \
--bind "$SOCKETDIR:/var/run/postgresql" \
orchestrator.sif \
python -m pipeline.orchestrator \
--db-dsn postgresql://127.0.0.1:5432/postgres \
--bio-service-url "$BIOCLIP_URL" \
--skip-bert \
--skip-qwen \
analyze --batch-size 16 >"$ORCH_LOG" 2>&1


echo "Done. Cleaning up..."

kill $BIO_PID
kill $PG_PID
