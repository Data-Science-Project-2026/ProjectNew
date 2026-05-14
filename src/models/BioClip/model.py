from __future__ import annotations

import os
import time
from contextlib import nullcontext
from io import BytesIO
from pathlib import Path
from typing import Sequence
import logging

import open_clip
from PIL import Image, UnidentifiedImageError
import torch


logger = logging.getLogger(__name__)


class BioClipModel:
    """Wrapper for BioCLIP image-text matching."""

    def __init__(
        self,
        *,
        species_tokens_path: Path | str,
        species_names_path: Path | str | None = None,
        model_name: str = "ViT-L-14",
        model_checkpoint_path: Path | str | None = None,
        allow_remote_model: bool = False,
        device: str | None = None,
        use_half: bool = False,
        text_batch_size: int = 2024,
    ) -> None:
        init_started = time.perf_counter()
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.use_half = use_half
        self.text_batch_size = int(text_batch_size)

        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        
        tokens_path = Path(species_tokens_path)
        names_path = Path(species_names_path) if species_names_path is not None else None
        checkpoint_path = Path(model_checkpoint_path) if model_checkpoint_path is not None else None

        if model_name.startswith("hf-hub:") and not allow_remote_model:
            raise RuntimeError(
                "Remote hf-hub model loading is disabled by default. "
                "Use a local model name (for example ViT-L-14) with model_checkpoint_path, "
                "or set allow_remote_model=True explicitly."
            )

        logger.info(
            "BioClip init started: device=%s use_half=%s text_batch_size=%d model=%s",
            self.device,
            self.use_half,
            self.text_batch_size,
            model_name,
        )

        t_model_load = time.perf_counter()
        model, _, preprocess = self._load_open_clip_model(
            model_name=model_name,
            model_checkpoint_path=checkpoint_path,
        )
        logger.info("BioClip model loaded in %.2fs", time.perf_counter() - t_model_load)

        t_model_move = time.perf_counter()
        model = model.to(self.device)
        if self.device == "cuda" and self.use_half:
            model.half()
        model.eval()
        logger.info("BioClip model moved to device/eval in %.2fs", time.perf_counter() - t_model_move)

        t_tokens = time.perf_counter()
        names, tokens = self._load_tokens(tokens_path, names_path)
        logger.info(
            "BioClip tokens loaded in %.2fs (token_count=%d)",
            time.perf_counter() - t_tokens,
            int(tokens.shape[0]),
        )
        self.model = model
        self.preprocess = preprocess
        self.names = names
        self.tokens = tokens

        t_cache = time.perf_counter()
        self.text_features = self._build_text_feature_cache()
        logger.info(
            "BioClip text cache ready in %.2fs (shape=%s)",
            time.perf_counter() - t_cache,
            tuple(self.text_features.shape),
        )

        # Force CUDA context initialization now so the first real inference
        # request is not delayed by 30-120 s of lazy GPU setup.
        if self.device == "cuda":
            t_warmup = time.perf_counter()
            logger.info("Running CUDA warmup pass to pre-initialize GPU context...")
            with torch.no_grad():
                dummy = torch.zeros(1, 3, 224, 224, device=self.device)
                if self.use_half:
                    dummy = dummy.half()
                _ = self.model.encode_image(dummy)
                torch.cuda.synchronize()
            logger.info("CUDA warmup complete in %.2fs", time.perf_counter() - t_warmup)

        logger.info("BioClip init complete in %.2fs", time.perf_counter() - init_started)

    def _build_text_feature_cache(self) -> torch.Tensor:
        """Compute normalized text embeddings once at startup for fast inference."""
        cache_started = time.perf_counter()
        features_chunks: list[torch.Tensor] = []
        total_text = self.tokens.shape[0]
        total_batches = (total_text + self.text_batch_size - 1) // self.text_batch_size

        logger.info(
            "Starting text cache build: total_tokens=%d batch_size=%d total_batches=%d",
            total_text,
            self.text_batch_size,
            total_batches,
        )

        with torch.no_grad():
            for batch_idx, i in enumerate(range(0, total_text, self.text_batch_size), start=1):
                batch_started = time.perf_counter()
                t_batch = self.tokens[i : i + self.text_batch_size].to(self.device)
                chunk = self.model.encode_text(t_batch)
                chunk = chunk / chunk.norm(dim=-1, keepdim=True)
                features_chunks.append(chunk)

                # Log every batch to make stalls explicit in startup logs.
                logger.info(
                    "Text cache batch %d/%d encoded in %.2fs (size=%d, elapsed=%.2fs)",
                    batch_idx,
                    total_batches,
                    time.perf_counter() - batch_started,
                    int(t_batch.shape[0]),
                    time.perf_counter() - cache_started,
                )

            features = torch.cat(features_chunks, dim=0)

        logger.info("Text cache build finished in %.2fs", time.perf_counter() - cache_started)

        return features

    def _load_open_clip_model(
        self, *, model_name: str, model_checkpoint_path: Path | None
    ):
        if model_checkpoint_path is not None:
            if not model_checkpoint_path.exists():
                raise RuntimeError(
                    f"Local BioCLIP checkpoint not found: {model_checkpoint_path}"
                )
            return open_clip.create_model_and_transforms(
                model_name,
                pretrained=str(model_checkpoint_path),
            )

        try:
            return open_clip.create_model_and_transforms(model_name)
        except Exception as exc:
            if model_name.startswith("hf-hub:"):
                raise RuntimeError(
                    "Failed to load BioCLIP from Hugging Face. "
                    "In offline environments, use a local model name and pass model_checkpoint_path "
                    "to a local checkpoint file."
                ) from exc
            raise

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
            logits = (100.0 * image_features @ self.text_features.T).cpu()
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
