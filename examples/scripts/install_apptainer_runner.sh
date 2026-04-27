#!/usr/bin/env bash
set -euo pipefail

echo "This environment is configured as no-install."
echo "Do not install packages here."
echo "Use only:"
echo "  1) module load python"
echo "  2) singularity commands with prebuilt .sif images"
echo ""
echo "If singularity is missing, request the module from your HPC admins."
exit 0
