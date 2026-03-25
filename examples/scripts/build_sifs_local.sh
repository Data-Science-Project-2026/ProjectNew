#!/usr/bin/env bash
set -euo pipefail

# Build SIF images locally (requires root privileges)
# Usage: sudo bash examples/scripts/build_sifs_local.sh

REPO_DIR=${REPO_DIR:-$PWD}

DEFS=(
  "${REPO_DIR}/src/models/BioClip-Container/Singularity.def"
  "${REPO_DIR}/src/models/Bert-Container/Singularity.def"
  "${REPO_DIR}/src/models/Qwen-Container/Singularity.def"
  "${REPO_DIR}/src/pipeline/Orchestrator-Container/Singularity.def"
)

SIFS=(
  "${REPO_DIR}/src/models/BioClip-Container/BioClip.sif"
  "${REPO_DIR}/src/models/Bert-Container/Bert.sif"
  "${REPO_DIR}/src/models/Qwen-Container/Qwen.sif"
  "${REPO_DIR}/src/pipeline/Orchestrator-Container/Orchestrator.sif"
)

if ! command -v apptainer &>/dev/null; then
  echo "apptainer not found in PATH. Install Apptainer on this host before running this script."
  exit 2
fi

if [ "$(id -u)" -ne 0 ]; then
  echo "Local builds require root. Please run with sudo."
  exit 3
fi

for i in "${!DEFS[@]}"; do
  def=${DEFS[$i]}
  sif=${SIFS[$i]}
  if [ ! -f "$def" ]; then
    echo "Skipping missing def: $def"
    continue
  fi
  echo "Building $sif from $def"
  apptainer build "$sif" "$def"
done

echo "Local SIF build complete."
