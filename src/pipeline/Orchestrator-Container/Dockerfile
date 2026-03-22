# Orchestrator container
FROM python:3.12-slim
WORKDIR /app

# copy entire workspace so imports resolve
COPY . /app

# install only the lightweight dependencies needed for orchestration
# (BioClip/Bert models run in their own containers, no torch needed here)
RUN pip install --no-cache-dir psycopg2-binary requests openai

ENV PYTHONPATH=/app/src

# entrypoint executes orchestrator CLI depending on args
ENTRYPOINT ["python", "-m", "pipeline.orchestrator"]
