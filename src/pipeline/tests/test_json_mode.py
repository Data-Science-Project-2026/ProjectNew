import json
import logging
from pathlib import Path


def test_json_mode_ingest_and_analyze(tmp_path, monkeypatch):
    # prepare CSV and image layout
    csv_dir = tmp_path / "csvs"
    images_root = tmp_path / "images"
    park_dir = images_root / "1Beijing_testpark"
    park_dir.mkdir(parents=True)

    # write a tiny image file
    img_path = park_dir / "alice_1.jpg"
    img_path.write_bytes(b"TESTIMAGE")

    # create a CSV with one post referencing the image
    csv_dir.mkdir()
    csv_file = csv_dir / "1Beijing_testpark.csv"
    # use header name expected by the orchestrator lookup logic
    csv_file.write_text("用户名,评论,image\nalice,Good park,alice_1.jpg\n", encoding="utf-8")

    # import the Pipeline and run in JSON/no-DB mode
    from pipeline.orchestrator import Pipeline

    pipeline = Pipeline(dsn="", bio_clip_args={}, bert_args={}, output_json=str(tmp_path / "results.json"), skip_qwen=True, skip_bio=True)

    # provide a fake bert model for analyze_posts
    class DummyBert:
        def batch_analyze(self, comments):
            return [{"sentiment_score": 0.9, "sentiment_label": "positive"} for _ in comments]

    monkeypatch.setattr(pipeline, "_get_bert_model", lambda: DummyBert())

    n = pipeline.ingest_posts(csv_dir, images_root=images_root)
    assert n == 1
    assert len(pipeline._json_store["posts"]) == 1
    assert len(pipeline._json_store["images"]) >= 1

    # run sentiment analysis (uses the patched bert model)
    scored = pipeline.analyze_posts()
    assert scored == 1
    assert pipeline._json_store["post_sentiment"][0]["score"] == 0.9

    # dump and validate written JSON
    pipeline.dump_results()
    data = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert "posts" in data and "images" in data and "post_sentiment" in data


def test_ingest_posts_recurses_into_subfolders(tmp_path):
    csv_root = tmp_path / "csv_root"
    nested = csv_root / "folder1"
    nested.mkdir(parents=True)

    csv_file = nested / "1NestedPark.csv"
    csv_file.write_text("用户名,评论\nalice,hello\n", encoding="utf-8")

    from pipeline.orchestrator import Pipeline

    pipeline = Pipeline(dsn="", bio_clip_args={}, bert_args={}, output_json=str(tmp_path / "results.json"), skip_bio=True, skip_bert=True, skip_qwen=True)

    n = pipeline.ingest_posts(csv_root)
    assert n == 1
    assert len(pipeline._json_store["posts"]) == 1


def test_ingest_progress_logging_for_csvs_and_images(tmp_path, caplog):
    csv_root = tmp_path / "csv_root"
    images_root = tmp_path / "images"
    csv_root.mkdir()
    images_root.mkdir()

    for idx in range(1, 3):
        nested = csv_root / f"folder{idx}"
        nested.mkdir()
        (nested / f"1Park{idx}.csv").write_text("用户名,评论\nalice,hello\n", encoding="utf-8")

    for idx in range(10):
        (images_root / f"alice_{idx}.jpg").write_bytes(b"img")

    from pipeline.orchestrator import Pipeline

    pipeline = Pipeline(dsn="", bio_clip_args={}, bert_args={}, output_json=str(tmp_path / "results.json"), skip_bio=True, skip_bert=True, skip_qwen=True)

    caplog.set_level(logging.INFO)
    pipeline.ingest_posts(csv_root)
    pipeline.ingest_images([images_root])

    assert "completed CSV" in caplog.text
    assert "(1/2)" in caplog.text
    assert "(2/2)" in caplog.text
    assert "Image ingestion progress: 10/10 ready" in caplog.text
