import shutil
import subprocess
import time
from pathlib import Path

import pytest

# ensure our package imports work regardless of where pytest is run
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from pipeline.orchestrator import Pipeline
from database import postgres as db

# simple DSN matching docker-compose.yml
TEST_DSN = "dbname=mydb user=myuser password=mypass host=localhost port=5432"


def _wait_for_postgres(dsn: str, timeout: int = 15) -> None:
    import psycopg2

    deadline = time.time() + timeout
    while True:
        try:
            conn = psycopg2.connect(dsn)
            conn.close()
            return
        except Exception:
            if time.time() > deadline:
                raise
            time.sleep(0.5)


@pytest.fixture(scope="module")
def services():
    # bring up the minimal set of containers needed for both tests
    subprocess.check_call(["docker-compose", "up", "-d", "postgres", "bioclip", "qwen"])
    _wait_for_postgres(TEST_DSN)
    yield
    # tear everything down at the end
    subprocess.check_call(["docker-compose", "down"])


@pytest.fixture
def sample_images(tmp_path):
    # copy three example JPGs into a temporary directory
    srcdir = Path("data/images/53深圳市宝安区西乡公园/class_0")
    dest = tmp_path / "imgs"
    dest.mkdir()
    for img in sorted(srcdir.glob("*.jpg"))[:3]:
        shutil.copy(img, dest / img.name)
    return dest


def test_bioclip_container(services, sample_images):
    pipeline = Pipeline(
        dsn=TEST_DSN,
        bio_clip_args={
            "species_tokens_path": Path("src/models/BioClip/species_tokens_latin.pt"),
            "species_names_path": Path("src/models/BioClip/species_names_latin.txt"),
            "use_half": False,
            "text_batch_size": 4048,
        },
        bio_service_url="http://localhost:5000",
        skip_bert=True,
        skip_qwen=True,
    )

    # ingest the three files and then analyse them via the container
    pipeline.ingest_images([sample_images], image_storage=sample_images)
    processed = pipeline.analyze_images(batch_size=3)
    assert processed == 3


def test_qwen_container(services, sample_images):
    pipeline = Pipeline(
        dsn=TEST_DSN,
        bio_clip_args={
            "species_tokens_path": Path("src/models/BioClip/species_tokens_latin.pt"),
            "species_names_path": Path("src/models/BioClip/species_names_latin.txt"),
            "use_half": False,
            "text_batch_size": 4048,
        },
        qwen_service_url="http://localhost:5002",
        skip_bio=True,
        skip_bert=True,
    )

    pipeline.ingest_images([sample_images], image_storage=sample_images)

    # create a dummy post and assign the ingested images to it
    with db.connect(TEST_DSN) as conn:
        db.insert_post(
            conn,
            city="test",
            park="test",
            username="",
            username_hash="",
            comment=None,
            time=None,
            rating=None,
        )
        # mark all existing images as belonging to post_id=1
        with conn.cursor() as cur:
            cur.execute("UPDATE images SET post_id = 1")
        conn.commit()

    # run Qwen on the single user
    result = pipeline.run_qwen(max_users=1)
    assert result >= 0
