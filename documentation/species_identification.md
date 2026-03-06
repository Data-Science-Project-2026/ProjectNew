# Species identification

This document describes the planned hybrid species-identification workflow in which BioCLIP remains the first-pass specialist model and Qwen3.5 acts as the second-pass verifier and semantic reasoner.

## Target role split

### BioCLIP

BioCLIP is responsible for:

* generating candidate species labels directly from the image embedding space;
* returning an initial confidence distribution over species tokens;
* providing a scalable first-pass filter for large image batches.

#### Pipeline image batch

Inside the orchestrator (`Pipeline.analyze_images`), the system repeatedly fetches a batch of images that have not yet been analyzed from the database. Each batch are then sent to the BioClip model for analysis.

#### BioCLIP species identification

BioCLIP compares two things:

- a set of **species tokens** (vector representations of species names), and
- a set of **image tokens** (vector representations of the input images).

The species tokens are fetched from a `.pt` file that contains the tokens that have been tokenized with BioClip beforehand.

##### 1) Incoming image batch is tokenized with the BioClip encoder

- The pipeline sends a batch of images as raw bytes.
- Each image is preprocessed and passed through the BioCLIP image encoder.
- This process produces the **image tokens**.

##### 2) Species tokens are compared to image tokens

- A similarity score between each image token and each species token is computed.
- A `text_batch_size` variable is used to limit the number of species tokens that are compared at a time, to preserve memory.

##### 3) Similarities become probabilities and tags

- Similarity scores are converted into probabilities over all candidate species.
- Only species with probability above a threshold (e.g. `0.05`) are kept.
- For each image in the batch the final result now includes
	- `species: list[str]`
	- `confidence: list[float]`

### Qwen3.5

Qwen3.5 is added after BioCLIP to:

* re-read the full image semantically;
* detect plants and animals using the structured image prompt in `src/models/Qwen/images.md`;
* provide contextual fields such as `image_summary` and `visible_species_in_image`;
* provide a second confidence signal that can be compared against BioCLIP.

## Planned orchestrator flow

Inside the orchestrator, the target image pipeline is:

1. Fetch an image batch from the database.
2. Run BioCLIP and obtain candidate species + confidence.
3. Run Qwen3.5 on the same image.
4. Read Qwen outputs from:
   * `plants_detected`
   * `animals_detected`
   * `visible_species_in_image`
5. Normalize the labels from both models into a comparable form.
6. Compute similarity between BioCLIP and Qwen predictions.
7. Produce a final fused species label and final fused confidence.

## Label normalization

Before fusion, the orchestrator should normalize both model outputs:

* prefer Latin scientific names;
* keep binomial names when available;
* fall back to genus-level labels such as `Quercus` when needed;
* treat `unknown` as a valid low-confidence placeholder but not as a strong match.

The normalization step should also strip trivial formatting differences such as:

* capitalization differences,
* repeated duplicates,
* list order differences.

## Similarity-based confidence fusion

Let:

* $b$ = BioCLIP confidence for a candidate,
* $q$ = Qwen confidence for the same candidate,
* $s$ = label similarity between the two model outputs.

An initial planning formula for the fused confidence is:

$$
c_{final} = 0.5b + 0.3q + 0.2s
$$

Recommended similarity levels:

* exact same binomial name: $s = 1.0$
* same genus but different species epithet: $s = 0.75$
* same coarse taxonomic group / partially matching label: $s = 0.5$
* no meaningful overlap: $s = 0.0$

If only one model returns a usable candidate, a conservative fallback is:

$$
c_{single} = 0.7 \times \max(b, q)
$$

This keeps single-model detections available while clearly separating them from true cross-model agreement.

## Final persistence plan

The target persistence pattern is:

* raw Qwen image-side outputs stay in `image_qwen_detail`;
* final fused species labels are written into `image_species`;
* the fused confidence is stored with the final species label;
* optional debugging metadata can keep the original BioCLIP score and Qwen score for later auditing.

## Why fusion

* BioCLIP is the specialized ecological classifier already used in the project.
* Qwen adds broader visual reasoning, and better handling of scene ambiguity.
* The combination is more stable than either model alone.

In short:

* **BioCLIP** = candidate generator
* **Qwen3.5** = verifier and contextual reasoner
* **fusion stage** = final confidence decision


