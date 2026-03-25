#!/usr/bin/env bash
set -euo pipefail

# Install Apptainer on an Ubuntu 22.04 (or similar) runner.
# This script requires sudo/root and installs dependencies then builds Apptainer from source.
# Use on a self-hosted runner where you control the environment.

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this script as root (sudo)."
  exit 1
fi

apt-get update
apt-get install -y \
  build-essential \
  libssl-dev \
  uuid-dev \
  libgpgme11-dev \
  squashfs-tools \
  libseccomp-dev \
  pkg-config \
  git \
  cryptsetup \
  wget \
  golang-go

# install Go (if packaged go is too old, user may replace this step)
export GOPATH=/root/go
mkdir -p "$GOPATH"

# Fetch Apptainer sources and build
APPTAINER_VERSION="1.2.0"  # adjust to desired version
cd /tmp
if [ -d apptainer ]; then rm -rf apptainer; fi
git clone https://github.com/apptainer/apptainer.git
cd apptainer
git checkout v${APPTAINER_VERSION} || true

./mconfig --prefix=/usr/local
make -C builddir
make -C builddir install

# Verify
if command -v apptainer &>/dev/null; then
  echo "Apptainer installed: $(apptainer --version)"
else
  echo "Apptainer build/install failed. Check build logs above."
  exit 2
fi
