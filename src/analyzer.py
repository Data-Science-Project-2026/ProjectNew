from __future__ import annotations

import sqlite3
from pathlib import Path

from database import sql
from models.BioClip.model import BioClipModel


class Analyzer:
	"""Analyze image blobs in the database with BioCLIP."""

	def __init__(
		self,
		*,
		db_path: str | Path,
		model: BioClipModel,
		batch_size: int = 8,
		threshold: float = 0.05,
	) -> None:
		self.db_path = str(db_path)
		self.model = model
		self.batch_size = int(batch_size)
		self.threshold = float(threshold)

	def analyze_images(self, max_batches: int | None = None) -> int:
		"""Analyze pending images and update the database.

		Returns the number of images processed.
		"""
		print("Starting image analysis")
		processed = 0
		with sqlite3.connect(self.db_path) as conn:
			sql.ensure_schema(conn)
			batches_run = 0
			while True:
				rows = sql.fetch_unanalyzed_images(conn, self.batch_size)
				if not rows:
					break

				print(
					f"Analyzing batch {batches_run + 1} with {len(rows)} images"
				)

				image_ids = [row[0] for row in rows]
				blobs = [row[1] for row in rows]
				results = self.model.analyze_image_blobs(
					blobs, threshold=self.threshold
				)

				for image_id, (species, confidence) in zip(image_ids, results):
					sql.update_image_analysis(
						conn,
						image_id=image_id,
						species=species,
						confidence=confidence,
					)
				conn.commit()

				processed += len(rows)
				batches_run += 1
				if max_batches is not None and batches_run >= max_batches:
					break

		return processed


def main() -> None:
	db_path = "src/database/data.db"
	species_tokens_path = Path("src/models/BioClip/species_tokens_latin.pt")
	species_names_path = Path("src/models/BioClip/species_names_latin.txt")
	batch_size = 1000
	threshold = 0.05
	use_half = False
	text_batch_size = 4048
	max_batches = 7

	model = BioClipModel(
		species_tokens_path=species_tokens_path,
		species_names_path=species_names_path,
		use_half=use_half,
		text_batch_size=text_batch_size,
	)
	analyzer = Analyzer(
		db_path=db_path,
		model=model,
		batch_size=batch_size,
		threshold=threshold,
	)
	processed = analyzer.analyze_images(max_batches=max_batches)
	print(f"Processed {processed} images")


if __name__ == "__main__":
	main()
