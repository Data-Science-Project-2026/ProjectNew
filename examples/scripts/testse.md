
## End-to-End Test Guide (Current Orchestrator, English)

### Step 0: Start the vLLM Qwen Inference Server

Use **multimodal mode** (do not use `--language-model-only`) because the
pipeline calls both image and comment endpoints.

```bash
sudo docker run --runtime nvidia --gpus all \
  -e HF_TOKEN \
  -e LD_LIBRARY_PATH="/usr/local/nvidia/lib64:/usr/lib/x86_64-linux-gnu:/usr/local/cuda/lib64" \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  --ipc=host \
  -p 8000:8000 \
  vllm/vllm-openai:cu130-nightly \
  Qwen/Qwen3.5-4B \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.7 \
  --kv-cache-dtype fp8 \
  --max-num-batched-tokens 2048
```

Wait until you see `Uvicorn running on http://0.0.0.0:8000`.

Quick check:

```bash
curl http://localhost:8000/v1/models
```

### Step 1: Build and Start Compose Services

```bash
cd /home/dream/Study/26p1/DSproject/ProjectNew

# Build images used in this test
sudo docker compose build qwen bert orchestrator

# Start required services
sudo docker compose up -d postgres bert qwen

# Wait for initialization
sleep 5

# Check status
sudo docker compose ps
```

### Step 2: Full Data Test (Current `data/3Tianjin`)

#### 2.1 Reset database (recommended for clean full test)

```bash
cd /home/dream/Study/26p1/DSproject/ProjectNew
sudo docker compose down -v
sudo docker compose up -d postgres bert qwen
sleep 5
```

#### 2.2 Ingest all posts and image links from the city folder

```bash
sudo docker compose run --rm --no-deps orchestrator \
  --db-dsn "dbname=mydb user=myuser password=mypass host=postgres port=5432" \
  --qwen-service-url http://qwen:5000 \
  --qwen-image-instruction-file /app/images.md \
  --qwen-comment-instruction-file /app/comment.md \
  --qwen-image-model "Qwen/Qwen3.5-4B" \
  --qwen-text-model "Qwen/Qwen3.5-4B" \
  --skip-bio --skip-bert \
  upload --csv-folder /data/3Tianjin --image-folder /data/3Tianjin --city Tianjin
```

#### 2.3 Run analysis (Bert + Qwen; skip BioClip)

```bash
sudo docker compose run --rm --no-deps orchestrator \
  --db-dsn "dbname=mydb user=myuser password=mypass host=postgres port=5432" \
  --bert-service-url http://bert:5000 \
  --qwen-service-url http://qwen:5000 \
  --qwen-image-instruction-file /app/images.md \
  --qwen-comment-instruction-file /app/comment.md \
  --qwen-image-model "Qwen/Qwen3.5-4B" \
  --qwen-text-model "Qwen/Qwen3.5-4B" \
  --skip-bio \
  analyze --batch-size 64 --workers 1
```

Note: For large image sets, this step can take a long time because Qwen image
analysis is executed per image.

### Step 3: Validate Results in PostgreSQL

```bash
sudo docker compose exec -T postgres psql -U myuser -d mydb \
  -c "SELECT COUNT(*) AS posts FROM posts;" \
  -c "SELECT COUNT(*) AS images FROM images;" \
  -c "SELECT COUNT(*) AS bert_done FROM posts WHERE bert_sentiment_score IS NOT NULL;" \
  -c "SELECT COUNT(*) AS qwen_done FROM posts WHERE qwen_sentiment_score IS NOT NULL;" \
  -c "SELECT COUNT(*) AS post_qwen_rows FROM post_qwen_detail;" \
  -c "SELECT COUNT(*) AS image_qwen_rows FROM image_qwen_detail;"
```

Detailed checks:

```sql
SELECT id, LEFT(comment, 60) AS comment,
       bert_sentiment_score, bert_sentiment_label,
       qwen_sentiment_score
FROM posts
ORDER BY id
LIMIT 10;

SELECT image_id, LEFT(image_summary, 100) AS summary
FROM image_qwen_detail
ORDER BY image_id
LIMIT 10;

SELECT post_id, emotions, text_activities_or_facilities
FROM post_qwen_detail
ORDER BY id DESC
LIMIT 5;
```

### Step 4: API Health Checks

```bash
# Bert endpoint
curl -s -X POST http://localhost:5001/analyze_posts \
  -H "Content-Type: application/json" \
  -d '{"comments":["This park is beautiful."]}'

# Qwen comment endpoint
curl -s -X POST http://localhost:5002/analyze_comments \
  -H "Content-Type: application/json" \
  -d '{"comments":["This park is beautiful."],"config":{"model":"Qwen/Qwen3.5-4B"}}'

# Qwen image endpoint (empty batch smoke test)
curl -s -X POST http://localhost:5002/analyze_images \
  -H "Content-Type: application/json" \
  -d '{"images":[],"config":{"model":"Qwen/Qwen3.5-4B"}}'
```

### Troubleshooting

```bash
sudo docker compose logs qwen --tail 100
sudo docker compose logs bert --tail 100
sudo docker compose logs postgres --tail 100
```

If Bert is up but requests fail intermittently right after startup, wait 30 to
60 seconds and retry while the model finishes loading.

### Key Notes

- Current orchestrator uses `upload-posts --city-folder ...` (not `--csv-dir`).
- Current orchestrator uses split Qwen endpoints:
  - `/analyze_images` for images
  - `/analyze_comments` for comments
- Do not pass removed CLI flags such as `--qwen-max-tokens` or `--qwen-temperature`.
- Bert and Qwen sentiment scores are stored independently.