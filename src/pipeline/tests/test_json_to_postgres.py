import json
from pathlib import Path


def test_insert_results_calls_db(monkeypatch, tmp_path):
    # sample JSON data produced by orchestrator
    data = {
        "posts": [
            {"id": 1, "city": "Beijing", "park": "TestPark", "username": "alice", "username_hash": "aaa", "comment": "Nice", "time": "2021-01-01", "rating": None}
        ],
        "images": [
            {"id": 10, "post_id": 1, "path": "/path/to/alice_1.jpg", "username_hash": "aaa"}
        ],
        "post_sentiment": [{"post_id": 1, "score": 0.5, "label": "neutral"}],
        "image_analysis": [],
        "image_qwen_detail": [],
        "post_qwen_detail": [],
    }

    # fake DB state to capture calls
    fake = {"posts": [], "images": [], "sentiment": [], "image_qwen": [], "post_qwen": []}

    class DummyConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    import database.postgres as db
    monkeypatch.setattr(db, "connect", lambda dsn: DummyConn())

    def ensure_schema(conn):
        return None

    def find_post_by_fingerprint(conn, fp):
        return None

    def insert_post(conn, city, park, username, username_hash, comment, time, rating):
        pid = len(fake["posts"]) + 1
        fake["posts"].append({"id": pid, "city": city, "park": park, "username": username})
        return pid

    def image_path_exists(conn, path):
        return False

    def insert_image(conn, post_id, path, username_hash=None):
        iid = len(fake["images"]) + 1
        fake["images"].append({"id": iid, "post_id": post_id, "path": path})
        return iid

    def update_bert_sentiment(conn, post_id, score, label=""):
        fake["sentiment"].append({"post_id": post_id, "score": score, "label": label})

    def update_image_analysis(conn, image_id, species, confidence):
        # record as best-effort
        fake.setdefault("image_analysis", []).append({"image_id": image_id, "species": species, "confidence": confidence})

    def insert_image_qwen_detail(conn, **kwargs):
        fake["image_qwen"].append(kwargs)

    def insert_post_qwen_detail(conn, **kwargs):
        fake["post_qwen"].append(kwargs)

    monkeypatch.setattr(db, "ensure_schema", ensure_schema)
    # database.postgres may not expose `find_post_by_fingerprint` in all setups;
    # allow adding it for the test.
    monkeypatch.setattr(db, "find_post_by_fingerprint", find_post_by_fingerprint, raising=False)
    monkeypatch.setattr(db, "insert_post", insert_post)
    monkeypatch.setattr(db, "image_path_exists", image_path_exists)
    monkeypatch.setattr(db, "insert_image", insert_image)
    monkeypatch.setattr(db, "update_bert_sentiment", update_bert_sentiment)
    monkeypatch.setattr(db, "update_image_analysis", update_image_analysis)
    monkeypatch.setattr(db, "insert_image_qwen_detail", insert_image_qwen_detail)
    monkeypatch.setattr(db, "insert_post_qwen_detail", insert_post_qwen_detail)

    # run the loader code
    from pipeline import json_to_postgres

    # call insert_results (should use the monkeypatched DB functions)
    json_to_postgres.insert_results("dsn", data)

    # verify that posts and images were inserted and sentiment updated
    assert len(fake["posts"]) == 1
    assert len(fake["images"]) == 1
    assert len(fake["sentiment"]) == 1
