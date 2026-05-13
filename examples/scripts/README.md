# Pipeline Execution Scripts

Production-ready scripts for running the data science pipeline in HPC (SLURM) environments.

## Overview

All scripts in this directory are SLURM job submission scripts designed for cluster execution. They use Singularity containers and PostgreSQL for data management. Before running any script, edit the following placeholders:

- `<path>` – absolute path to your project directory
- `<email>` – email for job notifications
- `<node>` – specific node name (if required)
- `<username>` – database username

## Scripts

### Database Setup

#### `start_postgres.sh`
Starts a PostgreSQL instance in a dedicated SLURM job. Required before any analysis.

**SLURM Config:**
- Partition: `long`
- CPUs: 1
- Memory: 1GB
- Time: 24 hours (long-running)

**Usage:**
```bash
sbatch start_postgres.sh
```

#### `db_dump.sh`
Creates a PostgreSQL database dump (backup) for disaster recovery and snapshots.

**Features:**
- Full database backup via `pg_dump`
- Supports remote PostgreSQL connections
- Output file: `mydb.dump`

**Usage:**
```bash
sbatch db_dump.sh
```

#### `restore_dump.sh`
Restores a PostgreSQL database from a dump file.

**Usage:**
```bash
sbatch restore_dump.sh
```

#### `load_material_postgres.sh`
Loads initial CSV data and images into PostgreSQL. Run this after `start_postgres.sh` and before analysis scripts.

**Usage:**
```bash
sbatch load_material_postgres.sh
```

---

### Analysis Services

These scripts start model analysis services on compute nodes (GPU or CPU) and interface with the orchestrator.

#### `bioclip_analyze.sh`
Species identification using BioClip (OpenCLIP-based). Runs on GPU nodes.

Before running the script these environmental variables must be given:

export SPECIES_TOKENS_PATH=/app/src/models/BioClip/species_tokens_latin.pt
export SPECIES_NAMES_PATH=/app/src/models/BioClip/species_names_latin.txt
export BIO_MODEL_CHECKPOINT_PATH=/app/src/models/BioClip/open_clip_pytorch_model.bin

**SLURM Config:**
- Partition: `gpu`
- GPUs: 1 (V100)
- CPUs per GPU: 8
- Memory per CPU: 4GB
- Time: 24 hours

**Features:**
- Analyzes images for species presence/detection
- Stores results in PostgreSQL
- Suitable for biodiversity monitoring

**Usage:**
```bash
sbatch bioclip_analyze.sh
```

#### `bert_analyze.sh`
Sentiment and psychological state analysis using BERT. Runs on CPU nodes.

**SLURM Config:**
- Partition: `long`
- CPUs: 4
- Memory: 8GB
- Time: varies

**Features:**
- Analyzes text comments for sentiment/emotions
- Scores posts with psychological state indicators
- Results stored in PostgreSQL

**Usage:**
```bash
sbatch bert_analyze.sh
```

#### `qwen_analyze.sh`
Advanced multimodal analysis using Qwen LLM (images + text).

**Features:**
- Detailed image descriptions
- Comment understanding and summarization
- Hybrid analysis combining vision and language
- Results stored in PostgreSQL

**Usage:**
```bash
sbatch qwen_analyze.sh
```

---

## Workflow Example

1. **Start PostgreSQL (required once per session):**
   ```bash
   sbatch start_postgres.sh
   watch squeue  # wait for job to complete
   ```

2. **Load data:**
   ```bash
   sbatch load_material_postgres.sh
   ```

3. **Run analysis (parallel or sequential):**
   ```bash
   sbatch bioclip_analyze.sh
   sbatch bert_analyze.sh
   sbatch qwen_analyze.sh
   ```

4. **Backup results:**
   ```bash
   sbatch db_dump.sh
   ```

---

## Environment Configuration

Edit the following in each script before submission:

- `module load Python cuDNN` – required modules for your cluster
- `source ../venv/bin/activate` – path to virtual environment
- `PGDATA`, `SOCKETDIR` – PostgreSQL data directories
- `--nodelist=<node>` – specific node allocation (optional)
- `--mail-user=<email>` – notification email

---

## Monitoring

Check job status:
```bash
squeue -u $USER
```

View logs:
```bash
tail -f logs/dsp2026-*.txt
```

---

## Database Troubleshooting

**PostgreSQL won't start:**
- Check `postmaster.pid` for stale processes
- Verify `$PGDATA` directory exists and is writable
- Check PostgreSQL logs in `$PGDATA/pg_log`

**Connection issues:**
- Ensure `start_postgres.sh` completed successfully
- Verify socket directory: `$SOCKETDIR`
- Check firewall/networking between nodes

---

## Performance Notes

- **BioClip** (GPU) is the longest-running analysis (~hours for large datasets)
- **BERT** (CPU) completes faster (~minutes to hours)
- **Qwen** (LLM) depends on model size and response time
- Run in parallel (sbatch multiple scripts) for fastest throughput
