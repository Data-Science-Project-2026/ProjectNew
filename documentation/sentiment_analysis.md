# Sentiment analysis

This document describes the planned sentiment workflow in which BERT remains the baseline model and Qwen3.5 becomes the semantic comparison layer.

## Target role split

### BERT

BERT remains responsible for:

* fast baseline sentiment scoring,
* stable numeric sentiment prediction,
* producing a first-pass sentiment label.

### Qwen3.5

Qwen3.5 is added after BERT to:

* analyze each comment with the structured prompt in `examples/comment.md`;
* extract emotions and their drivers;
* extract text-side species mentions;
* extract activity/facility mentions;
* produce a second sentiment score that can be compared with BERT.

## Planned orchestrator flow

The target comment pipeline is:

1. Fetch unscored comments from `posts`.
2. Run BERT first.
3. Store the BERT output in:
   * `posts.bert_sentiment_score`
   * `posts.bert_sentiment_label`
4. Run Qwen3.5 on the same comment using the per-comment JSON contract from `examples/comment.md`.
5. Store the Qwen sentiment output in `posts.qwen_sentiment_score`.
6. Compare BERT and Qwen sentiment results.
7. Write the fused final sentiment score into `posts.sentiment_score`.

## Agreement-based fusion

Let:

* $s_b$ = BERT sentiment score,
* $s_q$ = Qwen sentiment score.

The initial planning agreement score is:

$$
a = 1 - |s_b - s_q|
$$

An initial planning formula for the fused final sentiment is:

$$
s_{final} = 0.6s_b + 0.4s_q
$$

Under this plan:

* BERT stays the stronger baseline,
* Qwen acts as the semantic correction layer,
* agreement $a$ becomes the confidence / consistency signal.

If the gap between the two models is large, for example $|s_b - s_q| > 0.35$, the post can be marked as a disagreement case for later inspection.

## Additional Qwen text outputs

Qwen is not used only for the sentiment score. The same comment pass also provides structured fields for downstream analysis:

* `emotions`
* `influence_of_emotions`
* `text_species_mentions`
* `feeling_correlated_to_text_species`
* `text_activities_or_facilities`
* `feeling_correlated_to_text_activities_or_facilities`

These fields are important for the dashboard and for cross-modal interpretation, even when BERT remains the stronger sentiment baseline.

## Why fusion
* BERT is faster and more stable as a baseline sentiment scorer.
* Qwen adds richer reasoning about emotion, facilities, species mentions, and context.
* The comparison between the two models provides a better reliability signal than either model alone.

So the target logic is:

* **BERT** = baseline score
* **Qwen3.5** = semantic cross-check and text structure extraction
* **fusion stage** = final sentiment score

## Persistence planning

The current database schema already supports the core sentiment fields:

* `posts.bert_sentiment_score`
* `posts.bert_sentiment_label`
* `posts.qwen_sentiment_score`
* `posts.sentiment_score`

For the extra structured Qwen comment outputs, a dedicated post-level Qwen result table would be the cleanest long-term design. During transition, one-post Qwen batches can still reuse the existing Qwen persistence path if necessary.
