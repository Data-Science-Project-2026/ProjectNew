from __future__ import annotations

from contextlib import nullcontext
from io import BytesIO
from pathlib import Path
from typing import Sequence

import open_clip
from PIL import Image, UnidentifiedImageError
import torch


class BioClipModel:
    """Wrapper for BioCLIP image-text matching."""

    def __init__(
        self,
        *,
        species_tokens_path: Path,
        species_names_path: Path | None = None,
        model_name: str = "hf-hub:imageomics/bioclip-2",
        device: str | None = None,
        use_half: bool = False,
        text_batch_size: int = 2024,
    ) -> None:
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.use_half = use_half
        self.text_batch_size = int(text_batch_size)

        model, _, preprocess = open_clip.create_model_and_transforms(model_name)
        model = model.to(self.device)
        if self.device == "cuda" and self.use_half:
            model.half()
        model.eval()

        names, tokens = self._load_tokens(species_tokens_path, species_names_path)
        self.model = model
        self.preprocess = preprocess
        self.names = names
        self.tokens = tokens

    def _load_tokens(
        self, tokens_path: Path, species_names_path: Path | None
    ) -> tuple[list[str], torch.Tensor]:
        tok = torch.load(tokens_path, map_location="cpu")
        if isinstance(tok, dict):
            names = tok.get("names")
            tokens = tok.get("tokens")
            # Allow explicit names-file override so callers can keep output labels
            # as plain species names even when token prompts include full taxonomy.
            if species_names_path is not None:
                if not species_names_path.exists():
                    raise RuntimeError(f"Names file not found: {species_names_path}")
                names = species_names_path.read_text(encoding="utf-8").splitlines()
        else:
            tokens = tok
            names_file = species_names_path or tokens_path.with_name("species_names.txt")
            if names_file.exists():
                names = names_file.read_text(encoding="utf-8").splitlines()
            else:
                raise RuntimeError(
                    f"Could not determine names for tokens in {tokens_path}"
                )

        if names is None or tokens is None:
            raise RuntimeError(
                f"Token file {tokens_path} missing 'names' or 'tokens' entries"
            )

        if species_names_path is not None and hasattr(tokens, "shape") and len(names) != tokens.shape[0]:
            raise RuntimeError(
                "Names/tokens length mismatch after override "
                f"({len(names)} vs {tokens.shape[0]}) for {species_names_path}"
            )

        if hasattr(tokens, "shape") and len(names) != tokens.shape[0]:
            print(
                "Warning: names and tokens length mismatch "
                f"({len(names)} vs {getattr(tokens, 'shape', None)})"
            )

        tokens = tokens.to("cpu").long()
        return list(names), tokens

    def analyze_image_blobs(
        self, image_blobs: Sequence[bytes], *, threshold: float = 0.05
    ) -> list[tuple[list[str], list[float]]]:
        if not image_blobs:
            return []

        valid_indices: list[int] = []
        tensors: list[torch.Tensor] = []
        invalid_count = 0
        for idx, blob in enumerate(image_blobs):
            try:
                with Image.open(BytesIO(blob)) as image:
                    rgb_image = image.convert("RGB")
                tensors.append(self.preprocess(rgb_image))
                valid_indices.append(idx)
            except (UnidentifiedImageError, OSError, ValueError):
                invalid_count += 1

        if not tensors:
            if invalid_count:
                print(
                    f"Skipped {invalid_count} invalid image blob(s) in batch; no valid images to analyze"
                )
            return [([], []) for _ in image_blobs]

        if invalid_count:
            print(f"Skipped {invalid_count} invalid image blob(s) in batch")

        image_batch = torch.stack(tensors, dim=0).to(self.device)
        if self.device == "cuda" and self.use_half:
            image_batch = image_batch.half()

        amp_ctx = (
            torch.cuda.amp.autocast if (self.device == "cuda" and self.use_half) else None
        )
        ctx = amp_ctx() if amp_ctx is not None else nullcontext()

        with torch.no_grad(), ctx:
            image_features = self.model.encode_image(image_batch)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)

            logits_chunks = []
            total_text = self.tokens.shape[0]
            total_chunks = (total_text + self.text_batch_size - 1) // self.text_batch_size
            next_report_pct = 10
            for chunk_idx, i in enumerate(range(0, total_text, self.text_batch_size), start=1):
                t_batch = self.tokens[i : i + self.text_batch_size].to(self.device)
                text_features = self.model.encode_text(t_batch)
                text_features = text_features / text_features.norm(dim=-1, keepdim=True)
                logits_chunk = (100.0 * image_features @ text_features.T).cpu()
                logits_chunks.append(logits_chunk)
                del text_features, t_batch
                if self.device == "cuda":
                    torch.cuda.empty_cache()

                if total_chunks:
                    percent = int((chunk_idx / total_chunks) * 100)
                    if percent >= next_report_pct:
                        print(
                            f"Token comparison progress: {percent}% "
                        )
                        while percent >= next_report_pct:
                            next_report_pct += 10

            logits = torch.cat(logits_chunks, dim=-1)
            probs = logits.softmax(dim=-1)

        valid_results: list[tuple[list[str], list[float]]] = []
        cutoff = float(threshold)
        for row in probs:
            species: list[str] = []
            confidence: list[float] = []
            for idx, p in enumerate(row.tolist()):
                if p > cutoff:
                    label = self.names[idx] if idx < len(self.names) else f"idx_{idx}"
                    species.append(label)
                    confidence.append(float(p))
            valid_results.append((species, confidence))

        results: list[tuple[list[str], list[float]]] = [([], []) for _ in image_blobs]
        for source_idx, result in zip(valid_indices, valid_results):
            results[source_idx] = result

        return results
