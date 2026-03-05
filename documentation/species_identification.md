# Species identification

This document describes how species identification is performed in the project using BioCLIP.

## Pipeline image batch

Inside the orchestrator (`Pipeline.analyze_images`), the system repeatedly fetches a batch of images that have not yet been analyzed from the database. Each batch are then sent to the BioClip model for analysis.

## BioCLIP species identification

BioCLIP compares two things:

- a set of **species tokens** (vector representations of species names), and
- a set of **image tokens** (vector representations of the input images).

The species tokens are fetched from a `.pt` file that contains the tokens that have been tokenized with BioClip beforehand.

### 1) Incoming image batch is tokenized with the BioClip encoder

- The pipeline sends a batch of images as raw bytes.
- Each image is preprocessed and passed through the BioCLIP image encoder.

### 2) Species tokens are compared to image tokens

- A similarity score between each image token and each species token is computed.
- A `text_batch_size` variable is used to limit the number of species tokens that are compared at a time, to preserve memory.

### 3) Similarities become probabilities and tags

- Similarity scores are converted into probabilities over all candidate species.
- Only species with probability above a threshold (e.g. `0.05`) are kept.
- For each image in the batch the final result now includes
	- `species: list[str]`
	- `confidence: list[float]`
