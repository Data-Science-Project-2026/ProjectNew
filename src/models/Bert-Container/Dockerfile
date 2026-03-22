# Bert/Sentiment service container
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

# Install Python 3.12
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3-pip curl && \
    rm -rf /var/lib/apt/lists/* && \
    ln -sf /usr/bin/python3.12 /usr/bin/python

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r src/models/Bert-Container/requirements.txt

ENV PYTHONPATH=/app/src

CMD ["python", "src/models/Bert-Container/app.py"]
