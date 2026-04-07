# Running Models in HPC Environment (JSON Output Mode)

Since PostgreSQL is not accessible in your HPC environment, this guide explains how to run the pipeline directly with JSON output.

## Overview

The pipeline now supports **JSON mode** which:
- ✅ Requires **no database access** (no PostgreSQL)
- ✅ Stores all results in a **single JSON file**
- ✅ Works with **local models** or **remote services**
- ✅ Suitable for **batch HPC jobs** (SLURM, PBS, etc.)

## Quick Start

### 1. Basic Ingestion Only (Fastest)

No models, just ingest data:

```bash
python examples/scripts/run_json_pipeline.py \
  --csv-folder data/split_1/53深圳市宝安区西乡公园 \
  --image-folder data/split_1/53深圳市宝安区西乡公园/images \
  --output results.json
```

**Output:** `results.json` with posts and images metadata

### 2. With BioClip Image Analysis

If BioClip is available locally:

```bash
python examples/scripts/run_json_pipeline.py \
  --csv-folder data/split_1/53深圳市宝安区西乡公园 \
  --image-folder data/split_1/53深圳市宝安区西乡公园/images \
  --output results.json \
  --run-bio
```

Or with a BioClip service:

```bash
python examples/scripts/run_json_pipeline.py \
  --csv-folder data/split_1/... \
  --image-folder data/split_1/.../images \
  --bio-service-url http://localhost:5000 \
  --output results.json \
  --run-bio
```

### 3. Complete Analysis Pipeline

If all services are running:

```bash
python examples/scripts/run_json_pipeline.py \
  --csv-folder data/split_1/53深圳市宝安区西乡公园 \
  --image-folder data/split_1/53深圳市宝安区西乡公园/images \
  --qwen-service-url http://localhost:5002 \
  --output results.json \
  --run-qwen \
  --skip-bio --skip-bert  # Skip local models if not installed
```

## Command-Line Options

### Input Data
```
--csv-folder PATH              Folder with CSV files (posts/comments)
--image-folder PATH            Image folder(s) (can repeat multiple times)
--max-posts N                  Limit posts ingested (default: all)
--max-images N                 Limit images per stage (default: all)
```

### Output
```
--output FILE                  Required: output JSON file path
--log-file FILE                Optional: write logs to file (+ console)
```

### Models to Run
```
--run-bio                      Run BioClip image analysis
--run-bert                     Run BERT sentiment analysis  
--run-qwen                     Run Qwen multi-modal analysis
--skip-bio                     Don't load BioClip locally (use service instead)
--skip-bert                    Don't load BERT locally
--skip-qwen                    Don't load Qwen locally
```

### Service URLs (Optional)
```
--bio-service-url URL          BioClip service (e.g., http://localhost:5000)
--bert-service-url URL         BERT service (e.g., http://localhost:5001)
--qwen-service-url URL         Qwen service (e.g., http://localhost:5002)
```

### Processing
```
--batch-size N                 Batch size (default: 1000)
--workers N                    Number of threads (default: 1)
--debug                        Enable debug logging
```

## Example HPC Job Scripts

### SLURM (Singularity/Apptainer)

Save as `submit_pipeline.slurm`:

```bash
#!/bin/bash
#SBATCH --job-name=pipeline_json
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --output=pipeline_%j.log
#SBATCH --error=pipeline_%j.err

# Load required modules
module load python
module load singularity  # or apptainer

cd /path/to/ProjectNew

# Option 1: Run with local Python (if all deps installed)
python examples/scripts/run_json_pipeline.py \
  --csv-folder data/split_1/53深圳市宝安区西乡公园 \
  --image-folder data/split_1/53深圳市宝安区西乡公园/images \
  --output results.json \
  --workers 4 \
  --run-qwen \
  --skip-bio --skip-bert

# Or Option 2: Run inside Singularity container
singularity exec \
  --bind /path/to/ProjectNew:/app \
  /path/to/image.sif \
  python /app/examples/scripts/run_json_pipeline.py \
    --csv-folder /app/data/split_1/... \
    --image-folder /app/data/split_1/.../images \
    --output /app/results.json
```

Submit with:
```bash
sbatch submit_pipeline.slurm
```

### PBS/Torque

Save as `submit_pipeline.pbs`:

```bash
#!/bin/bash
#PBS -N pipeline_json
#PBS -l walltime=04:00:00
#PBS -l nodes=1:ppn=4
#PBS -l mem=32gb
#PBS -o pipeline.log
#PBS -e pipeline.err

cd $PBS_O_WORKDIR

python examples/scripts/run_json_pipeline.py \
  --csv-folder data/split_1/53深圳市宝安区西乡公园 \
  --image-folder data/split_1/53深圳市宝安区西乡公园/images \
  --output results.json \
  --workers 4
```

Submit with:
```bash
qsub submit_pipeline.pbs
```

## Running Model Services on HPC

If you want to use model services on HPC, start them before running the pipeline:

### Using Apptainer Instances

```bash
# Start BioClip, Bert, and Qwen as background instances
apptainer instance start \
  --bind $(pwd):/app \
  --nv \
  BioClip.sif bioclip

apptainer instance start \
  --bind $(pwd):/app \
  --nv \
  Bert.sif bert

apptainer instance start \
  --bind $(pwd):/app \
  Qwen.sif qwen

# Wait for initialization
sleep 10

# Run pipeline pointing to these services
python examples/scripts/run_json_pipeline.py \
  --csv-folder data/... \
  --image-folder data/.../images \
  --bio-service-url http://127.0.0.1:5000 \
  --bert-service-url http://127.0.0.1:5001 \
  --qwen-service-url http://127.0.0.1:5002 \
  --output results.json

# Stop instances when done
apptainer instance stop bioclip bert qwen
```

## Output JSON Structure

The output JSON contains all ingested and analyzed data:

```json
{
  "posts": [
    {
      "id": 1,
      "city": "Beijing",
      "park": "park_name",
      "username_hash": "sha256_hash",
      "comment": "user comment text",
      "time": "2024-01-15 10:30:00",
      "rating": 4.5
    }
  ],
  "images": [
    {
      "id": 1,
      "post_id": 1,
      "username_hash": "sha256_hash",
      "path": "/path/to/image.jpg"
    }
  ],
  "image_analysis": [
    {
      "image_id": 1,
      "species": ["Species A", "Species B"],
      "confidence": [0.85, 0.72]
    }
  ],
  "post_sentiment": [
    {
      "post_id": 1,
      "sentiment_score": 0.78,
      "sentiment_label": "positive"
    }
  ],
  "image_qwen_detail": [
    {
      "image_id": 1,
      "image_summary": "A park scene...",
      "plants_detected": [...],
      "animals_detected": [...],
      "human_activities_detected": [...]
    }
  ],
  "post_qwen_detail": [
    {
      "post_id": 1,
      "analysis": {...}
    }
  ],
  "ingestion_status": [
    {
      "filename": "path/to/file.csv",
      "status": "done",
      "last_processed_row": 150
    }
  ]
}
```

## Troubleshooting

### "ModuleNotFoundError: No module named 'pytorch_lightning'" or similar

You're missing model dependencies. Either:
1. Install them: `pip install torch transformers pytorch_lightning`
2. Use `--skip-*` flags and service URLs instead
3. Run inside a container where deps are pre-installed

### Service connection errors

If using service URLs (e.g., `--bio-service-url http://localhost:5000`):
- Make sure the service is actually running and accessible
- Check the service is listening on the right port
- Verify network connectivity between nodes (if distributed)

### Out of memory errors

- Reduce `--batch-size` (default 1000 may be too large)
- Reduce `--max-images` or process fewer posts
- Use `--workers 1` to reduce parallelism

### Pipeline hangs or slow progress

- Check service logs if using remote services
- Increase `--workers` for parallel processing
- Monitor system resources (CPU, memory, I/O)

## Running Only Specific Stages

You can run individual stages by combining flags:

```bash
# Only ingestion (no models)
python examples/scripts/run_json_pipeline.py \
  --csv-folder data/... \
  --image-folder data/.../images \
  --output results.json

# Ingestion + Qwen only
python examples/scripts/run_json_pipeline.py \
  --csv-folder data/... \
  --image-folder data/.../images \
  --output results.json \
  --run-qwen

# Just BioClip (assumes images already ingested)
python examples/scripts/run_json_pipeline.py \
  --image-folder data/.../images \
  --output results.json \
  --run-bio
```

## Next Steps After Pipeline Completion

Once you have the `results.json`:

1. **Parse and analyze** results with Python:
   ```python
   import json
   with open('results.json') as f:
       data = json.load(f)
   
   print(f"Posts analyzed: {len(data['posts'])}")
   print(f"Images analyzed: {len(data['image_analysis'])}")
   ```

2. **Export to database** (if needed):
   ```bash
   python src/pipeline/json_to_postgres.py \
     --json-file results.json \
     --psql-dsn "postgresql://user:pass@host/db"
   ```

3. **Generate visualizations** or reports from the JSON

## See Also

- [Pipeline Documentation](../pipeline.md) - Detailed pipeline architecture
- [Apptainer Setup](../apptainer.md) - Building and running containers
- [Database Setup](../database.md) - For later ingestion into PostgreSQL (optional)
