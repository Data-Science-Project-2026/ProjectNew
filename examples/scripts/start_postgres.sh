#!/bin/bash
#SBATCH --job-name=start_postgres
#SBATCH -o <path>/logs/dsp2026-%J.txt
#SBATCH -p long
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=24:00:00

echo "Running in node: $(hostname)"
echo "Running in: $(pwd)"

DATA=<path>/ProjectNew
PGDATA=<path>/ProjectNew/pgdata
SOCKETDIR=<path>/ProjectNew/pgsocket

mkdir -p "$PGDATA"
mkdir -p "$SOCKETDIR"

echo "PGDATA: $PGDATA"
echo "SOCKETDIR: $SOCKETDIR"

if [ -f "$PGDATA/postmaster.pid" ]; then
  echo "Found existing postmaster.pid"
  OLD_PID=$(head -n 1 "$PGDATA/postmaster.pid")
  if ps -p "$OLD_PID" > /dev/null 2>&1; then 
    echo "Postgres already running with PID $OLD_PID"
    echo "Aborting to avoid corruption"
    exit 1
  else
    echo "Removing stale postmaster.pid"
    rm -f "$PGDATA/postmaster.pid"
  fi
fi

if [ ! -f "$PGDATA/PG_VERSION" ]; then
  echo "Initializing new database..."
  singularity exec \
    --bind "$PGDATA:/data" \
    postgres.sif \
    initdb -D /data
  if [ $? -ne 0 ]; then
    echo "initdb failed"
    exit 1
  fi
fi

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

echo "Active processes:"
ps aux | grep postgres | grep -v grep

echo "Postgres running"
echo "Socket: $SOCKETDIR"

echo "HOST=$(hostname)"
ss -ltnp | grep 5432 || echo "NO TCP LISTEN"
singularity exec postgres.sif pg_isready -h 127.0.0.1 -p 5432 -d postgres || echo "Postgres readiness check (informational)"

wait $PG_PID

