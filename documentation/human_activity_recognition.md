# Human activity recognition

This document describes the planned human-activity workflow for the orchestrator.

## Model choice

Human activity recognition is planned as a **Qwen3.5-only** task.

The rationale is:

* activities depend on posture, interaction, and scene context;
* the same Qwen image pass already sees people, objects, and surroundings together;
* BioCLIP is designed for species, not activities;
* BERT is text-only and is not relevant for image-side activity detection.

## Input contract

For each image, Qwen should return at least:

* `human_activities_detected`

The same response can also contain:

* `image_summary`
* `landscape_elements`
* `visible_species_in_image`

These additional fields help interpret the activity in context.

## Planned orchestrator flow

1. Fetch the image record.
2. Send the image to the Qwen endpoint.
3. Parse the returned JSON.
4. Normalize activity labels into concise English forms such as:
   * `walking`
   * `climbing`
   * `taking photos`
   * `cycling`
   * `birdwatching`
5. Deduplicate labels per image.
6. Persist `human_activities_detected` to `image_qwen_detail.human_activities_detected`.
7. Persist the full structured Qwen response to `image_qwen_detail.raw_response` for debugging and later dashboard use.

## Confidence policy

When Qwen returns structured entries in `human_activities_detected`, the orchestrator should keep the model-provided confidence value as the primary confidence signal.

If Qwen only returns a free-form activity list and no structured confidence entries, the activity may still be stored, but it should be treated as lower-confidence metadata.


## Relation to the rest of the pipeline

Human activity recognition should not be implemented as a separate image pass if the same Qwen call is already being used for species verification and object/scene understanding.

Instead, one Qwen image inference should feed three downstream consumers:

1. species verification,
2. human activity recognition,
3. scene/object metadata extraction.

This keeps the orchestrator efficient and ensures that all visual outputs are derived from the same interpretation of the image.
