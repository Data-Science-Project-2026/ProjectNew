#!/bin/bash
#SBATCH --job-name=pg_dump
#SBATCH -o <path>/logs/dump-%J.txt
#SBATCH -p long
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=00:15:00
#SBATCH --nodelist=<node>

echo "Running in node: $(hostname)"

DATA=<path>/ProjectNew
OUT=$DATA/dumps
mkdir -p "$OUT"

DB_HOST=127.0.0.1
DB_PORT=5432
DB_USER=<username>
DB_NAME=postgres

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DUMP_FILE="/data/dumps/dump_${TIMESTAMP}.sql"

echo "Dumping database to: $DUMP_FILE"

singularity exec \
--bind $DATA:/data \
postgres.sif \
pg_dump \
-h $DB_HOST \
-p $DB_PORT \
-U $DB_USER \
-d $DB_NAME \
-F p \
-f "$DUMP_FILE" &&

echo "Dump finished"
