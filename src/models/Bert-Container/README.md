# Bert/Sentiment Container

Provides sentiment analysis as a service.  URL:
`POST /analyze_posts` with `{ "comments": ["string", ...] }`, returns
`{ "scores": [{"sentiment_score": ...}, ...] }`.

Build & run:

```sh
cd src/models/Bert-Container
docker build -t bert-service .
docker run -p 5001:5000 bert-service
```

Optional `SENTIMENT_MODEL` environment variable allows choosing a different
HuggingFace model.
