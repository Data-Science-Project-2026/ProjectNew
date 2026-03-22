# Qwen service container
FROM python:3.12-slim
WORKDIR /app

COPY . /app

RUN apt-get update && apt-get install -y --no-install-recommends \
	python3 python3-venv python3-pip curl \
	&& rm -rf /var/lib/apt/lists/* \
	&& ln -sf /usr/bin/python3 /usr/bin/python

RUN pip install --no-cache-dir -r src/models/Qwen-Container/requirements.txt

ENV PYTHONPATH=/app/src

CMD ["python", "src/models/Qwen-Container/app.py"]
