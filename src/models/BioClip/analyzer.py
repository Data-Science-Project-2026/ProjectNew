from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, Sequence, Optional

from database import postgres as db
from models.BioClip.model import BioClipModel

logger = logging.getLogger(__name__)


class BioClipAnalyzer:
    """Run batch image analysis against a Postgres backend.

    The orchestrator is expected to copy incoming images into a shared
    filesystem directory (``image_root``) using the database ID as the
    filename.  This class repeatedly queries ``fetch_unanalyzed_images`` to
    obtain the next batch of IDs and then loads the corresponding files
    before dispatching them to a ``BioClipModel`` instance.
    """

    def __init__(
        self,
        dsn: str,
        model: BioClipModel,
        batch_size: int = 1000,
        threshold: float = 0.05,
        image_root: Optional[Path] = None,
    ) -> None:
        self.dsn = dsn
        self.model = model
        self.batch_size = int(batch_size)
        self.threshold = float(threshold)
        self.image_root = Path(image_root) if image_root is not None else Path("data/images")
        self.image_root.mkdir(parents=True, exist_ok=True)

    def analyze_images(self, max_batches: int | None = None, workers: int = 1) -> int:
        """Process all unscored images and write results back to Postgres.

        ``max_batches`` limits the number of batches processed per worker (useful
        for testing).  ``workers`` controls concurrent database connections
        and model invocations.
        """
        total = 0

        def _worker() -> int:
            processed = 0
            with db.connect(self.dsn) as conn:
                while True:
                    rows = db.fetch_unanalyzed_images(conn, self.batch_size)
                    if not rows:
                        break
                    ids, _hashes = zip(*rows)

                    blobs: list[bytes] = []
                    for img_id in ids:
                        candidates = list(self.image_root.glob(f"{img_id}.*"))
                        if not candidates:
                            logger.warning("image file for id %s not found", img_id)
                            blobs.append(b"")
                            continue
                        try:
                            with open(candidates[0], "rb") as f:
                                blobs.append(f.read())
                        except Exception:
                            logger.exception("failed to read image %s", candidates[0])
                            blobs.append(b"")

                    if self.model is None:
                        results = [([], []) for _ in blobs]
                    else:
                        results = self.model.analyze_image_blobs(blobs, threshold=self.threshold)

                    for img_id, (species, confidence) in zip(ids, results):
                        db.update_image_analysis(
                            conn, image_id=img_id, species=species, confidence=confidence
                        )
                    processed += len(rows)
                    if max_batches is not None and processed >= self.batch_size * max_batches:
                        break
            return processed

        if workers <= 1:
            total = _worker()
        else:
            with ThreadPoolExecutor(max_workers=workers) as exe:
                futures = [exe.submit(_worker) for _ in range(workers)]
                for fut in as_completed(futures):
                    total += fut.result()
        return total


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Standalone BioCLIP analyzer")
    parser.add_argument("--db-dsn", required=True, help="Postgres DSN to write results to")
    parser.add_argument("--image-root", default="data/images", help="directory where images are stored")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--threshold", type=float, default=0.05)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--species-tokens", default="src/models/BioClip/species_tokens_latin.pt")
    parser.add_argument("--species-names", default="src/models/BioClip/species_names_latin.txt")
    parser.add_argument("--use-half", action="store_true")
    parser.add_argument("--text-batch-size", type=int, default=4048)
    args = parser.parse_args()

    try:
        model = BioClipModel(
            species_tokens_path=Path(args.species_tokens),
            species_names_path=Path(args.species_names),
            use_half=args.use_half,
            text_batch_size=args.text_batch_size,
        )
    except FileNotFoundError as e:
        logger.warning("BioClip tokens not found: %s; analysis will be no-op", e)
        model = None  # type: ignore

    analyzer = BioClipAnalyzer(
        dsn=args.db_dsn,
        model=model,
        batch_size=args.batch_size,
        threshold=args.threshold,
        image_root=Path(args.image_root),
    )

    count = analyzer.analyze_images(max_batches=args.max_batches, workers=args.workers)
    print(f"processed {count} images")
