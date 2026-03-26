#!/usr/bin/env bash
set -euo pipefail

# Start a temporary local PostgreSQL server inside your job/allocation.
# - Uses initdb/pg_ctl if available (no root required).
# - Creates a test user and database for quick pipeline testing.
# - On exit (Ctrl-C) the server is stopped and data remains in PGDATA.

REPO_DIR=${REPO_DIR:-$PWD}
PGDATA=${PGDATA:-"${REPO_DIR}/pgdata"}
PGPORT=${PGPORT:-5432}
PGUSER=${PGUSER:-dsuser}
PGPASS=${PGPASS:-dspass}
DBNAME=${DBNAME:-dsdb}

echo "Using REPO_DIR=$REPO_DIR"
echo "PGDATA=$PGDATA, PGPORT=$PGPORT"

if command -v ss >/dev/null 2>&1; then
  if ss -ltn | awk '{print $4}' | grep -q ":${PGPORT}$"; then
    echo "Port ${PGPORT} already listening. If that's a Postgres you can use it instead of this script."
    exit 1
  fi
fi

if ! command -v initdb >/dev/null 2>&1 || ! command -v pg_ctl >/dev/null 2>&1; then
  cat <<'MSG'
initdb or pg_ctl not found in PATH.
You can either:
 - load a postgres module (e.g. `module load postgresql`) if your cluster provides one, or
 - ask admins to install postgres client/server tools, or
 - run Postgres inside an Apptainer/Singularity container (see documentation/apptainer.md).

This script requires the `initdb` and `pg_ctl` commands to initialize and run a local test database.
MSG
  exit 2
fi

mkdir -p "${PGDATA}"
chown -R "$(id -u):$(id -g)" "${PGDATA}" || true

if [ -z "$(ls -A "${PGDATA}")" ]; then
  echo "Initializing database in ${PGDATA}"
  initdb -D "${PGDATA}"
fi

echo "Starting Postgres..."
pg_ctl -D "${PGDATA}" -o "-F -p ${PGPORT} -h 127.0.0.1" -w start

cleanup() {
  echo "Stopping Postgres..."
  pg_ctl -D "${PGDATA}" -m fast stop || true
  exit 0
}
trap cleanup INT TERM EXIT

# create user and database (ignore errors if already exist)
echo "Creating user '${PGUSER}' and database '${DBNAME}' (if missing)"
psql -p "${PGPORT}" -v ON_ERROR_STOP=1 --username="$(whoami)" --no-password <<SQL || true
CREATE USER ${PGUSER} WITH PASSWORD '${PGPASS}';
CREATE DATABASE ${DBNAME} OWNER ${PGUSER};
\q
SQL

DSN="postgresql://${PGUSER}:${PGPASS}@127.0.0.1:${PGPORT}/${DBNAME}"
echo "Postgres is running. Connection DSN: ${DSN}"
echo "You can run the orchestrator with e.g."
echo "  python -m pipeline.orchestrator --dsn \"${DSN}\" upload-images --folders /data --image-root /data/images"

echo "Server will run until you press Ctrl-C."
while true; do sleep 86400; done
