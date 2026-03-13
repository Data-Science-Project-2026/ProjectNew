#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
MODE="${1:-all}"
INTERVAL="${2:-15}"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/watch_qwen_progress.sh [all|image|comment|bert] [interval_seconds]

Examples:
  bash scripts/watch_qwen_progress.sh
  bash scripts/watch_qwen_progress.sh image 10
  bash scripts/watch_qwen_progress.sh comment 5

Environment:
  PROJECT_DIR=/abs/path/to/ProjectNew   Override compose project directory
EOF
}

case "$MODE" in
  all|image|comment|bert) ;;
  -h|--help) usage; exit 0 ;;
  *)
    echo "Unknown mode: $MODE" >&2
    usage
    exit 1
    ;;
esac

sudo -v
( while true; do sleep 60; sudo -n true >/dev/null 2>&1 || exit; done ) &
SUDO_KEEPALIVE_PID=$!
trap 'kill "$SUDO_KEEPALIVE_PID" >/dev/null 2>&1 || true' EXIT

pct() {
  local done="$1"
  local total="$2"
  awk -v d="$done" -v t="$total" 'BEGIN { if (t == 0) { printf "0.0" } else { printf "%.1f", (100.0 * d / t) } }'
}

fetch_counts() {
  sudo docker compose --project-directory "$PROJECT_DIR" exec -T postgres \
    psql -U myuser -d mydb -At -F $'\t' -P pager=off \
    -c "SELECT
          (SELECT COUNT(*) FROM posts),
          (SELECT COUNT(*) FROM posts WHERE comment IS NOT NULL AND BTRIM(comment) <> ''),
          (SELECT COUNT(*) FROM images),
          (SELECT COUNT(*) FROM posts WHERE bert_sentiment_score IS NOT NULL),
          (SELECT COUNT(*) FROM post_qwen_detail),
          (SELECT COUNT(*) FROM posts WHERE qwen_sentiment_score IS NOT NULL),
          (SELECT COUNT(*) FROM image_qwen_detail),
          COALESCE((SELECT TO_CHAR(MAX(created_at), 'YYYY-MM-DD HH24:MI:SS') FROM post_qwen_detail), '-'),
          COALESCE((SELECT TO_CHAR(MAX(created_at), 'YYYY-MM-DD HH24:MI:SS') FROM image_qwen_detail), '-')
        ;"
}

while true; do
  IFS=$'\t' read -r total_posts total_comment_posts total_images bert_done qwen_comment_rows qwen_sent_done qwen_image_rows last_comment_ts last_image_ts < <(fetch_counts)

  image_remaining=$((total_images - qwen_image_rows))
  comment_remaining=$((total_comment_posts - qwen_comment_rows))
  bert_remaining=$((total_comment_posts - bert_done))

  image_pct="$(pct "$qwen_image_rows" "$total_images")"
  comment_pct="$(pct "$qwen_comment_rows" "$total_comment_posts")"
  bert_pct="$(pct "$bert_done" "$total_comment_posts")"
  qwen_sent_pct="$(pct "$qwen_sent_done" "$total_comment_posts")"

  clear
  echo "Qwen/Bert progress monitor"
  echo "Project: $PROJECT_DIR"
  echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
  echo

  case "$MODE" in
    all)
      printf 'Posts total                : %s\n' "$total_posts"
      printf 'Posts with comments        : %s\n' "$total_comment_posts"
      printf 'Images total               : %s\n' "$total_images"
      echo
      printf 'Bert done                  : %s / %s (%s%%)\n' "$bert_done" "$total_comment_posts" "$bert_pct"
      printf 'Bert remaining             : %s\n' "$bert_remaining"
      echo
      printf 'Qwen image rows            : %s / %s (%s%%)\n' "$qwen_image_rows" "$total_images" "$image_pct"
      printf 'Qwen image remaining       : %s\n' "$image_remaining"
      printf 'Last image_qwen_detail row : %s\n' "$last_image_ts"
      echo
      printf 'Qwen comment rows          : %s / %s (%s%%)\n' "$qwen_comment_rows" "$total_comment_posts" "$comment_pct"
      printf 'Qwen comment remaining     : %s\n' "$comment_remaining"
      printf 'Qwen sentiment updated     : %s / %s (%s%%)\n' "$qwen_sent_done" "$total_comment_posts" "$qwen_sent_pct"
      printf 'Last post_qwen_detail row  : %s\n' "$last_comment_ts"
      ;;
    image)
      printf 'Images total               : %s\n' "$total_images"
      printf 'Qwen image rows            : %s / %s (%s%%)\n' "$qwen_image_rows" "$total_images" "$image_pct"
      printf 'Qwen image remaining       : %s\n' "$image_remaining"
      printf 'Last image_qwen_detail row : %s\n' "$last_image_ts"
      ;;
    comment)
      printf 'Posts with comments        : %s\n' "$total_comment_posts"
      printf 'Qwen comment rows          : %s / %s (%s%%)\n' "$qwen_comment_rows" "$total_comment_posts" "$comment_pct"
      printf 'Qwen comment remaining     : %s\n' "$comment_remaining"
      printf 'Qwen sentiment updated     : %s / %s (%s%%)\n' "$qwen_sent_done" "$total_comment_posts" "$qwen_sent_pct"
      printf 'Last post_qwen_detail row  : %s\n' "$last_comment_ts"
      ;;
    bert)
      printf 'Posts with comments        : %s\n' "$total_comment_posts"
      printf 'Bert done                  : %s / %s (%s%%)\n' "$bert_done" "$total_comment_posts" "$bert_pct"
      printf 'Bert remaining             : %s\n' "$bert_remaining"
      ;;
  esac

  echo
  echo "Refresh interval: ${INTERVAL}s"
  echo "Press Ctrl+C to stop"
  sleep "$INTERVAL"
done