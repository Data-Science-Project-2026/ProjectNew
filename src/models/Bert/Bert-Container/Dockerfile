# Bert/Sentiment service container
FROM python:3.12-slim
WORKDIR /app

COPY ../../.. /app

RUN pip install --no-cache-dir -r src/models/Bert/Bert-Container/requirements.txt

ENV PYTHONPATH=/app/src

CMD ["python", "src/models/Bert/Bert-Container/app.py"]
