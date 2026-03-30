# Bert/Sentiment service container
FROM python:3.12-slim

# Install Python 3.12
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY src /app/src

RUN pip install --no-cache-dir -r src/models/Bert-Container/requirements.txt

ENV PYTHONPATH=/app/src

CMD ["python", "src/models/Bert-Container/app.py"]
