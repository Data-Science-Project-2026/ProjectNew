#!/bin/bash
#SBATCH --job-name=bert_analyze
#SBATCH -o <path>/logs/dsp2026-%J.txt
#SBATCH -p long
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --mail-type=END
#SBATCH --mail-user=<email>
#SBATCH --nodelist=<node>

echo "Running in node: $(hostname)"
echo "Running in: $(pwd)"

module load Python cuDNN
source ../venv/bin/activate

DATA=<path>/ProjectNew
USER=<username>

echo "Starting Bert..."

singularity exec \
bert-service.sif \
python /app/src/models/Bert-Container/app.py &

BERT_PID=$!

echo "Waiting for Bert..."
for i in {1..30}; do
  if curl -s http://127.0.0.1:5001/health > /dev/null; then
    echo "Bert is up"
    break
  fi
  sleep 2
done

sleep 50

echo "Running orchestrator..."

singularity exec \
--bind $DATA:/data \
orchestrator.sif \
python -m pipeline.orchestrator \
--db-dsn postgresql://$USER@127.0.0.1:5432/postgres \
--skip-bio \
--bert-service-url http://127.0.0.1:5000 \
--skip-qwen \
analyze --batch-size 512


echo "Done. Cleaning up..."

kill $BERT_PID
