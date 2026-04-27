import importlib.util
import json
from pathlib import Path


def _load_run_json_pipeline_module():
    script_path = Path(__file__).resolve().parents[3] / "examples" / "scripts" / "run_json_pipeline.py"
    spec = importlib.util.spec_from_file_location("run_json_pipeline_module", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_run_json_pipeline_writes_incremental_checkpoints(tmp_path, monkeypatch):
    module = _load_run_json_pipeline_module()

    csv_root = tmp_path / "csvs"
    image_root = tmp_path / "images"
    csv_root.mkdir()
    image_root.mkdir()
    output_json = tmp_path / "results.json"

    observations = {"checkpoint_seen_before_analysis": False}

    class DummyPipeline:
        def __init__(self, *args, output_json=None, **kwargs):
            self.output_json = output_json
            self._json_store = {
                "posts": [],
                "images": [],
                "ingestion_status": [],
                "post_sentiment": [],
                "post_qwen_detail": [],
                "image_qwen_detail": [],
            }

        def ingest_posts(self, csv_folder, images_root=None, max_posts=None, debug=False):
            self._json_store["posts"].append({"id": 1, "comment": "hello"})
            return 1

        def ingest_images(self, folders, image_storage=None):
            self._json_store["images"].append({"id": 1, "path": "img.jpg"})
            return 1

        def analyze_images(self, batch_size=1000, workers=1):
            data = json.loads(output_json.read_text(encoding="utf-8"))
            observations["checkpoint_seen_before_analysis"] = (
                data["pipeline_run"]["stage"] == "images_ingested"
                and data["pipeline_run"]["status"] == "running"
                and data["pipeline_run"]["posts_ingested"] == 1
                and data["pipeline_run"]["images_ingested"] == 1
            )
            return 1

        def analyze_posts(self, batch_size=1000, workers=1):
            self._json_store["post_sentiment"].append({"post_id": 1, "score": 0.5})
            return 1

        def run_qwen_image_analysis(self, max_images=None):
            self._json_store["image_qwen_detail"].append({"image_id": 1})
            return 1

        def run_qwen_comment_analysis(self, max_posts=None):
            self._json_store["post_qwen_detail"].append({"post_id": 1})
            return 1

        def dump_results(self, path=None):
            destination = Path(path or self.output_json)
            destination.write_text(json.dumps(self._json_store), encoding="utf-8")

    monkeypatch.setattr(module, "Pipeline", DummyPipeline)

    rc = module.run_pipeline_json_mode(
        csv_folder=csv_root,
        image_folders=[image_root],
        output_json=output_json,
        max_posts=None,
        max_images=None,
        batch_size=10,
        workers=1,
        bio_service_url=None,
        bert_service_url=None,
        qwen_service_url=None,
        run_bio=True,
        run_bert=True,
        run_qwen=True,
        qwen_image_model="test-image-model",
        qwen_text_model="test-text-model",
        qwen_image_instruction_file=None,
        qwen_comment_instruction_file=None,
        debug=False,
    )

    assert rc == 0
    assert observations["checkpoint_seen_before_analysis"] is True

    final_data = json.loads(output_json.read_text(encoding="utf-8"))
    assert final_data["pipeline_run"]["stage"] == "completed"
    assert final_data["pipeline_run"]["status"] == "completed"
    assert final_data["pipeline_run"]["posts_ingested"] == 1
    assert final_data["pipeline_run"]["images_ingested"] == 1