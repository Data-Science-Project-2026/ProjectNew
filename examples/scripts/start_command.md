sudo docker run --runtime nvidia --gpus all \
    -e HF_TOKEN \
    -e LD_LIBRARY_PATH="/usr/local/nvidia/lib64:/usr/lib/x86_64-linux-gnu:/usr/local/cuda/lib64" \
    -v ~/.cache/huggingface:/root/.cache/huggingface \
    --ipc=host \
    -p 8000:8000 \
    vllm/vllm-openai:latest \
    Qwen/Qwen3-VL-8B-Instruct-FP8 \
    --max-model-len 8192 \
    --limit-mm-per-prompt.video 0 \
    --gpu-memory-utilization 0.85 \
    --kv-cache-dtype fp8

sudo docker run --runtime nvidia --gpus all     -e HF_TOKEN     -e LD_LIBRARY_PATH="/usr/local/nvidia/lib64:/usr/lib/x86_64-linux-gnu:/usr/local/cuda/lib64"     -v ~/.cache/huggingface:/root/.cache/huggingface     --ipc=host     -p 8000:8000     vllm/vllm-openai:cu130-nightly     Qwen/Qwen3.5-4B     --max-model-len 8192     --language-model-only     --gpu-memory-utilization 0.7     --kv-cache-dtype fp8     --max-num-batched-tokens 2048

sudo docker run --runtime nvidia --gpus all     -e HF_TOKEN     -e LD_LIBRARY_PATH="/usr/local/nvidia/lib64:/usr/lib/x86_64-linux-gnu:/usr/local/cuda/lib64"     -v ~/.cache/huggingface:/root/.cache/huggingface     --ipc=host     -p 8000:8000     vllm/vllm-openai:cu130-nightly     Qwen/Qwen3.5-4B     --max-model-len 8192    --gpu-memory-utilization 0.7     --kv-cache-dtype fp8     --max-num-batched-tokens 2048


