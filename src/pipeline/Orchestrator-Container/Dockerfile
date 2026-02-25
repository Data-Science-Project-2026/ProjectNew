# Orchestrator container
FROM python:3.12-slim
WORKDIR /app

# copy entire workspace so imports resolve
COPY ../../.. /app

# install dependencies: reuse requirements from other containers and add extras
RUN pip install --no-cache-dir psycopg2-binary flask requests openai \
    open_clip_torch transformers torch

ENV PYTHONPATH=/app/src

# entrypoint executes orchestrator CLI depending on args
ENTRYPOINT ["python", "-m", "pipeline.orchestrator"]
