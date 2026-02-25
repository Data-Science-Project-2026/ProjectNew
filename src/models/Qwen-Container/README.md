# Qwen Container

Flask service for running the Qwen multimodal model.  It expects a POST to
`/analyze_users` with a JSON body containing `"batches"`, where each batch
is the dictionary version of a `QwenUserBatchInput`.

It replies with `{"results":[...parsed results...]}`.

Build & run:

```sh
cd src/models/Qwen-Container
docker build -t qwen-service .
docker run -p 5002:5000 qwen-service
```

Provide your OpenAI API key via `OPENAI_API_KEY` environment variable when
running the container.
