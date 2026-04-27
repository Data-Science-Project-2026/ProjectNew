# Scripts for Pipeline Execution

This directory contains helper scripts for running the pipeline in various environments.

## JSON Pipeline (No PostgreSQL)

For HPC environments without PostgreSQL access, use the JSON pipeline scripts:

### `run_json_pipeline.py`

Main Python script that runs the complete pipeline with JSON output (no database required).

**Features:**
- ✅ No PostgreSQL dependency
- ✅ Supports local models or remote services
- ✅ Ingests CSV posts and images
- ✅ Runs optional analysis (BioClip, BERT, Qwen)
- ✅ Outputs all results to single JSON file
- ✅ HPC-friendly with batch/parallel processing

**Quick start:**
```bash
python examples/scripts/run_json_pipeline.py \
  --csv-folder data/split_1/park_name \
  --image-folder data/split_1/park_name/images \
  --output results.json
```

See `--help` for all options or read [json_pipeline_hpc.md](../documentation/json_pipeline_hpc.md) for detailed guide.

### `submit_json_pipeline.sh`

Bash helper for submitting pipeline jobs to HPC clusters (SLURM or PBS).

**Features:**
- Auto-detects SLURM (sbatch) or PBS (qsub)
- Generates job scripts with appropriate directives
- Supports all pipeline options
- Loads `python` via environment modules in job scripts
- Optional Singularity execution via `--singularity-image`
- Can do dry-run (--dry-run) to preview without submitting

**Quick start:**
```bash
./examples/scripts/submit_json_pipeline.sh \
  --csv-folder data/split_1/park_name \
  --image-folder data/split_1/park_name/images \
  --output results.json \
  --singularity-image /path/to/pipeline.sif \
  --time 04:00:00 \
  --cpus 4 \
  --memory 32G
```

## Other Scripts

### `pipeline_to_json.py`

Lightweight helper for quick testing with images and optional service calls. Works directly with image and comment files without CSV ingestion.

### `run_pipeline_on_node.sh`

Example script for running the pipeline on a single HPC node using Singularity instances. Starts BioClip, BERT, and Qwen as isolated containers and points the orchestrator to them.

### `install_apptainer_runner.sh`

No-install policy helper. It intentionally does not install anything and prints
guidance to use only `module load python` plus `singularity` with prebuilt SIF images.

### `watch_qwen_progress.sh`

Monitors Qwen model progress in real-time by watching log files.

### `export_results_snapshot.py`

Exports/converts pipeline results from one format to another.

## Recommended Workflow for HPC

No-install policy for this environment:
- Use only `module load python`
- Use only `singularity` commands with prebuilt `.sif` images
- Do not use `pip install`, `apt-get`, or container build steps on cluster nodes

1. **Test locally first:**
   ```bash
   python examples/scripts/run_json_pipeline.py \
     --csv-folder data/... \
     --image-folder data/.../images \
     --output test_results.json \
     --max-posts 20 \
     --max-images 50
   ```

2. **Check the output:**
   ```bash
   python -c "import json; data=json.load(open('test_results.json')); print(f'Posts: {len(data[\"posts\"])}, Images: {len(data[\"images\"])}')"
   ```

3. **Submit to cluster:**
   ```bash
   ./submit_json_pipeline.sh \
     --csv-folder data/split_1/... \
     --image-folder data/split_1/.../images \
     --output results.json \
     --cpus 8 \
     --memory 64G
   ```

4. **Monitor job:**
   ```bash
   # SLURM
   squeue -u $USER
   tail -f results_*.log
   
   # PBS
   qstat -u $USER
   tail -f results_*.log
   ```

## Environment Variables

These can be set to change pipeline behavior:

```bash
# Skip local model loading (use services instead)
export SKIP_BIO=1
export SKIP_BERT=1
export SKIP_QWEN=1

# Set batch size
export BATCH_SIZE=500

# Set worker threads
export WORKERS=4

python examples/scripts/run_json_pipeline.py --csv-folder ... --output ...
```

## Troubleshooting

**"ModuleNotFoundError: No module named..."**
- In this HPC environment, do not install dependencies.
- Use `--skip-*` flags and service URLs, or run with `--singularity-image`.

**Service connection errors**
- Ensure services are running and ports are accessible
- Check firewall rules on HPC cluster
- Use `--bio-service-url http://localhost:5000` for local containers

**Out of memory**
- Reduce `--batch-size` (try 100 or 500)
- Reduce `--max-images` or `--max-posts`
- Use `--workers 1` to reduce parallelism

**Slow processing**
- Increase `--workers` for more threads
- Increase `--cpus` in job submission
- Use `--batch-size` appropriate for your hardware

## Documentation

- [JSON Pipeline HPC Guide](../../documentation/json_pipeline_hpc.md) - Detailed guide for HPC
- [Pipeline Architecture](../../documentation/pipeline.md) - Overall pipeline design
- [Apptainer Setup](../../documentation/apptainer.md) - Building containers for HPC
- [Database Setup](../../documentation/database.md) - For loading results into PostgreSQL (optional)
