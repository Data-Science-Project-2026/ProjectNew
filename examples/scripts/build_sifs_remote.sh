#!/usr/bin/env bash
set -euo pipefail

# Build SIF images using Apptainer remote builder (no root required locally)
# Usage: bash examples/scripts/build_sifs_remote.sh

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
  echo "apptainer (or singularity) not found in PATH. Install Apptainer CLI before running."
  exit 2
fi

for i in "${!DEFS[@]}"; do
  def=${DEFS[$i]}
  sif=${SIFS[$i]}
  if [ ! -f "$def" ]; then
    echo "Skipping missing def: $def"
    continue
  fi
  echo "Building (remote) $sif from $def"
  apptainer build --remote "$sif" "$def"
  echo "Built $sif"
done

echo "Remote SIF build complete. Artifacts are in the repository paths above."
