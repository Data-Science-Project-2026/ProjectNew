#!/bin/bash
#SBATCH --job-name=pg_restore_test
#SBATCH -o <path>/logs/restore-%J.txt
#SBATCH -p long
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=00:30:00
#SBATCH --nodelist=<node>

echo "Running in node: $(hostname)"

DATA=<path>/ProjectNew
DUMP=/data/dumps/dump_20260425_124559.sql

DB_HOST=127.0.0.1
DB_PORT=5432
DB_USER=<username>
TEST_DB=test_db

echo "Restoring dump into $TEST_DB"

singularity exec \
  --bind $DATA:/data \
  postgres.sif \
  bash -c "
    echo 'Dropping old test_db (if exists)...'
    dropdb -h $DB_HOST -p $DB_PORT -U $DB_USER $TEST_DB 2>/dev/null || true

    echo 'Creating test_db...'
    createdb -h $DB_HOST -p $DB_PORT -U $DB_USER $TEST_DB

    echo 'Restoring dump...'
    psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $TEST_DB -f $DUMP
  "

echo "Restore finished"
