# BioClip service container
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

# Install Python 3.12
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip curl && \
    rm -rf /var/lib/apt/lists/* && \
    ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app

# copy entire workspace so imports still work
COPY src /app/src

# install requirements (torch with CUDA support)
RUN pip install --no-cache-dir -r src/models/BioClip-Container/requirements.txt

ENV PYTHONPATH=/app/src

CMD ["python", "src/models/BioClip-Container/app.py"]
