# BioClip service container
FROM python:3.12-slim
WORKDIR /app

# copy entire workspace so imports still work
COPY ../../.. /app

# install requirements
RUN pip install --no-cache-dir -r src/models/BioClip-Container/requirements.txt

ENV PYTHONPATH=/app/src

CMD ["python", "src/models/BioClip-Container/app.py"]
