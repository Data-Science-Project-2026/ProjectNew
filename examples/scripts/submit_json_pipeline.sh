#!/bin/bash
# HPC Job Submission Helper for JSON Pipeline
# 
# Usage:
#   ./submit_json_pipeline.sh --csv-folder /path/to/csv \
#                             --image-folder /path/to/images \
#                             --output results.json
#
# Submits job to SLURM/PBS depending on what's available

set -euo pipefail

# Default values
CSV_FOLDER=""
IMAGE_FOLDERS=()
OUTPUT_FILE=""
TIME_LIMIT="04:00:00"
CPUS=4
MEMORY="32G"
PARTITION=""
QUEUE=""
JOB_NAME="pipeline_json"
DRY_RUN=0
WORKER_THREADS=1
SKIP_BIO=0
SKIP_BERT=0
SKIP_QWEN=0
RUN_BIO=0
RUN_BERT=0
RUN_QWEN=0
BIO_URL=""
BERT_URL=""
QWEN_URL=""
MAX_POSTS=""
MAX_IMAGES=""
BATCH_SIZE="1000"
SINGULARITY_IMAGE=""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

usage() {
    cat << 'EOF'
Submit JSON pipeline job to HPC cluster

USAGE:
  ./submit_json_pipeline.sh --csv-folder PATH --image-folder PATH --output FILE [options]

REQUIRED:
  --csv-folder FOLDER        CSV files directory
  --image-folder FOLDER      Image files directory (can repeat)
  --output FILE              Output JSON file path

OPTIONAL:
  --time TIME                Walltime limit (default: 04:00:00)
  --cpus N                   Number of CPUs (default: 4)
  --memory MEM               Memory size (default: 32G)
  --partition PAR            Partition/queue name (SLURM)
  --job-name NAME            Job name (default: pipeline_json)
  
  MODEL OPTIONS:
  --run-bio                  Run BioClip analysis
  --run-bert                 Run BERT analysis
  --run-qwen                 Run Qwen analysis
  --skip-bio                 Skip BioClip (don't load locally)
  --skip-bert                Skip BERT (don't load locally)
  --skip-qwen                Skip Qwen (don't load locally)
  
  SERVICE URLs:
  --bio-service-url URL      BioClip service URL
  --bert-service-url URL     BERT service URL
  --qwen-service-url URL     Qwen service URL
  
  PROCESSING:
  --workers N                Number of worker threads (default: 1)
  --batch-size N             Batch size (default: 1000)
  --max-posts N              Max posts to process
  --max-images N             Max images to process
  
  --dry-run                  Show job script without submitting
    --singularity-image PATH   Optional .sif image to run pipeline inside singularity
  --help                     Show this help

EXAMPLES:
  # Basic ingestion only
  ./submit_json_pipeline.sh \\
    --csv-folder data/split_1/city_park \\
    --image-folder data/split_1/city_park/images \\
    --output results.json

  # With Qwen and services
  ./submit_json_pipeline.sh \\
    --csv-folder data/split_1/city_park \\
    --image-folder data/split_1/city_park/images \\
    --output results.json \\
    --qwen-service-url http://localhost:5002 \\
    --run-qwen \\
    --workers 4

  # Quick test (1000 images max)
  ./submit_json_pipeline.sh \\
    --csv-folder data/split_1/city_park \\
    --image-folder data/split_1/city_park/images \\
    --output results.json \\
    --max-images 1000 \\
    --time 01:00:00
EOF
    exit 1
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --csv-folder)
            CSV_FOLDER="$2"
            shift 2
            ;;
        --image-folder)
            IMAGE_FOLDERS+=("$2")
            shift 2
            ;;
        --output)
            OUTPUT_FILE="$2"
            shift 2
            ;;
        --time)
            TIME_LIMIT="$2"
            shift 2
            ;;
        --cpus)
            CPUS="$2"
            shift 2
            ;;
        --memory)
            MEMORY="$2"
            shift 2
            ;;
        --partition)
            PARTITION="$2"
            shift 2
            ;;
        --queue)
            QUEUE="$2"
            shift 2
            ;;
        --job-name)
            JOB_NAME="$2"
            shift 2
            ;;
        --workers)
            WORKER_THREADS="$2"
            shift 2
            ;;
        --batch-size)
            BATCH_SIZE="$2"
            shift 2
            ;;
        --max-posts)
            MAX_POSTS="$2"
            shift 2
            ;;
        --max-images)
            MAX_IMAGES="$2"
            shift 2
            ;;
        --run-bio)
            RUN_BIO=1
            shift
            ;;
        --run-bert)
            RUN_BERT=1
            shift
            ;;
        --run-qwen)
            RUN_QWEN=1
            shift
            ;;
        --skip-bio)
            SKIP_BIO=1
            shift
            ;;
        --skip-bert)
            SKIP_BERT=1
            shift
            ;;
        --skip-qwen)
            SKIP_QWEN=1
            shift
            ;;
        --bio-service-url)
            BIO_URL="$2"
            shift 2
            ;;
        --bert-service-url)
            BERT_URL="$2"
            shift 2
            ;;
        --qwen-service-url)
            QWEN_URL="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --singularity-image)
            SINGULARITY_IMAGE="$2"
            shift 2
            ;;
        --help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# Validation
if [[ -z "$CSV_FOLDER" ]] || [[ -z "$OUTPUT_FILE" ]] || [[ ${#IMAGE_FOLDERS[@]} -eq 0 ]]; then
    echo -e "${RED}Error: --csv-folder, --image-folder, and --output are required${NC}"
    usage
fi

if [[ ! -d "$CSV_FOLDER" ]]; then
    echo -e "${RED}Error: CSV folder not found: $CSV_FOLDER${NC}"
    exit 1
fi

for img_folder in "${IMAGE_FOLDERS[@]}"; do
    if [[ ! -d "$img_folder" ]]; then
        echo -e "${RED}Error: Image folder not found: $img_folder${NC}"
        exit 1
    fi
done

# Get repo directory
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Create Python command
PYTHON_ARGS="python examples/scripts/run_json_pipeline.py"
PYTHON_ARGS="$PYTHON_ARGS --csv-folder $CSV_FOLDER"
for img_folder in "${IMAGE_FOLDERS[@]}"; do
    PYTHON_ARGS="$PYTHON_ARGS --image-folder $img_folder"
done
PYTHON_ARGS="$PYTHON_ARGS --output $OUTPUT_FILE"
PYTHON_ARGS="$PYTHON_ARGS --batch-size $BATCH_SIZE"
PYTHON_ARGS="$PYTHON_ARGS --workers $WORKER_THREADS"

[[ -n "$MAX_POSTS" ]] && PYTHON_ARGS="$PYTHON_ARGS --max-posts $MAX_POSTS"
[[ -n "$MAX_IMAGES" ]] && PYTHON_ARGS="$PYTHON_ARGS --max-images $MAX_IMAGES"

[[ $RUN_BIO -eq 1 ]] && PYTHON_ARGS="$PYTHON_ARGS --run-bio"
[[ $RUN_BERT -eq 1 ]] && PYTHON_ARGS="$PYTHON_ARGS --run-bert"
[[ $RUN_QWEN -eq 1 ]] && PYTHON_ARGS="$PYTHON_ARGS --run-qwen"

[[ $SKIP_BIO -eq 1 ]] && PYTHON_ARGS="$PYTHON_ARGS --skip-bio"
[[ $SKIP_BERT -eq 1 ]] && PYTHON_ARGS="$PYTHON_ARGS --skip-bert"
[[ $SKIP_QWEN -eq 1 ]] && PYTHON_ARGS="$PYTHON_ARGS --skip-qwen"

[[ -n "$BIO_URL" ]] && PYTHON_ARGS="$PYTHON_ARGS --bio-service-url $BIO_URL"
[[ -n "$BERT_URL" ]] && PYTHON_ARGS="$PYTHON_ARGS --bert-service-url $BERT_URL"
[[ -n "$QWEN_URL" ]] && PYTHON_ARGS="$PYTHON_ARGS --qwen-service-url $QWEN_URL"

RUN_COMMAND="$PYTHON_ARGS"
if [[ -n "$SINGULARITY_IMAGE" ]]; then
    RUN_COMMAND="singularity exec --bind $REPO_DIR:/app --pwd /app $SINGULARITY_IMAGE $PYTHON_ARGS"
fi

# Detect job scheduler
if command -v sbatch &> /dev/null; then
    SCHEDULER="slurm"
elif command -v qsub &> /dev/null; then
    SCHEDULER="pbs"
else
    echo -e "${RED}Error: No job scheduler found (SLURM sbatch or PBS qsub)${NC}"
    exit 1
fi

# Generate job script
generate_slurm_script() {
    cat << SLURM_SCRIPT
#!/bin/bash
#SBATCH --job-name=$JOB_NAME
#SBATCH --time=$TIME_LIMIT
#SBATCH --cpus-per-task=$CPUS
#SBATCH --mem=$MEMORY
#SBATCH --output=${OUTPUT_FILE%.json}_%j.log
#SBATCH --error=${OUTPUT_FILE%.json}_%j.err
SLURM_SCRIPT
    if [[ -n "$PARTITION" ]]; then
        echo "#SBATCH --partition=$PARTITION" >> /dev/stdout
    fi
    
    cat << 'SLURM_SCRIPT_BODY'

# Load modules
module load python

if ! command -v python >/dev/null 2>&1; then
    echo "python command not found after module load python"
    exit 2
fi

if [[ -n "SINGULARITY_IMAGE_PLACEHOLDER" ]]; then
    if ! command -v singularity >/dev/null 2>&1; then
        echo "singularity command not found"
        exit 3
    fi
fi

cd REPO_DIR_PLACEHOLDER
$RUN_COMMAND_PLACEHOLDER
SLURM_SCRIPT_BODY
}

generate_pbs_script() {
    cat << PBS_SCRIPT
#!/bin/bash
#PBS -N $JOB_NAME
#PBS -l walltime=$TIME_LIMIT
#PBS -l nodes=1:ppn=$CPUS
#PBS -l mem=${MEMORY}b
#PBS -o ${OUTPUT_FILE%.json}_\$PBS_JOBID.log
#PBS -e ${OUTPUT_FILE%.json}_\$PBS_JOBID.err
PBS_SCRIPT
    if [[ -n "$QUEUE" ]]; then
        echo "#PBS -q $QUEUE" >> /dev/stdout
    fi
    
    cat << 'PBS_SCRIPT_BODY'

    module load python

    if ! command -v python >/dev/null 2>&1; then
        echo "python command not found after module load python"
        exit 2
    fi

    if [[ -n "SINGULARITY_IMAGE_PLACEHOLDER" ]]; then
        if ! command -v singularity >/dev/null 2>&1; then
            echo "singularity command not found"
            exit 3
        fi
    fi

cd $PBS_O_WORKDIR
    $RUN_COMMAND_PLACEHOLDER
PBS_SCRIPT_BODY
}

# Create temporary job script
SCRIPT_FILE=$(mktemp)
trap "rm -f $SCRIPT_FILE" EXIT

if [[ "$SCHEDULER" == "slurm" ]]; then
    generate_slurm_script > "$SCRIPT_FILE"
else
    generate_pbs_script > "$SCRIPT_FILE"
fi

# Replace placeholders
sed -i "s|REPO_DIR_PLACEHOLDER|$REPO_DIR|g" "$SCRIPT_FILE"
sed -i "s|\$RUN_COMMAND_PLACEHOLDER|$RUN_COMMAND|g" "$SCRIPT_FILE"
sed -i "s|SINGULARITY_IMAGE_PLACEHOLDER|$SINGULARITY_IMAGE|g" "$SCRIPT_FILE"

# Show script
echo -e "${BLUE}=== Job Script ===${NC}"
cat "$SCRIPT_FILE"
echo -e "${BLUE}==================${NC}"

# Submit or dry-run
if [[ $DRY_RUN -eq 1 ]]; then
    echo -e "${BLUE}Dry-run mode (no submission)${NC}"
else
    if [[ "$SCHEDULER" == "slurm" ]]; then
        echo -e "${GREEN}Submitting to SLURM...${NC}"
        JOB_ID=$(sbatch "$SCRIPT_FILE" | awk '{print $NF}')
        echo -e "${GREEN}Job submitted: $JOB_ID${NC}"
    else
        echo -e "${GREEN}Submitting to PBS...${NC}"
        JOB_ID=$(qsub "$SCRIPT_FILE")
        echo -e "${GREEN}Job submitted: $JOB_ID${NC}"
    fi
fi
