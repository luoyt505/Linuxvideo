"""API 接口测试（基于 FastAPI TestClient）。

若环境中缺少 httpx，相关用例会自动跳过（fastapi.testclient 依赖 httpx）。
"""
from __future__ import annotations

import pytest

pytest.importorskip("httpx", reason="TestClient 需要 httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")
    assert "database" in data
    assert "ffmpeg" in data
    assert "task_queue" in data


def test_media_list_empty(db, client):
    response = client.get("/api/media")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["page"] == 1


def test_media_list_with_data(client, sample_items):
    response = client.get("/api/media")
    data = response.json()
    assert data["total"] == 3

    videos = client.get("/api/media?media_type=video").json()
    assert videos["total"] == 1
    assert videos["items"][0]["filename"] == "a.mp4"

    year_2024 = client.get("/api/media?year=2024").json()
    assert year_2024["total"] == 2

    searched = client.get("/api/media?q=演示音频").json()
    assert searched["total"] == 1
    assert searched["items"][0]["media_type"] == "audio"


def test_media_pagination_and_sort(client, sample_items):
    page = client.get("/api/media?page=1&page_size=2&sort=size&order=desc").json()
    assert page["total"] == 3
    assert page["pages"] == 2
    assert len(page["items"]) == 2
    assert page["items"][0]["size"] >= page["items"][1]["size"]


def test_media_detail_and_404(client, sample_items):
    item_id = sample_items[0].id
    detail = client.get(f"/api/media/{item_id}").json()
    assert detail["id"] == item_id
    assert detail["media_type"] == "video"

    missing = client.get("/api/media/999999")
    assert missing.status_code == 404


def test_library_stats(client, sample_items):
    data = client.get("/api/library/stats").json()
    assert data["total_items"] == 3
    assert data["by_type"]["video"] == 1
    assert data["by_type"]["audio"] == 1
    assert data["by_type"]["image"] == 1
    assert data["total_size"] == sum(item.size for item in sample_items)


def test_library_dirs(client, sample_items):
    data = client.get("/api/library/dirs").json()
    assert isinstance(data["media_dirs"], list)
    assert data["media_dirs"], "测试环境应通过 MEDIA_DIRS 配置至少一个目录"
    assert "transcode_dir" in data
    assert "cache_dir" in data


def test_scan_endpoint(client, media_dir):
    import time

    (media_dir / "api_scan.mp4").write_bytes(b"\x00" * 1024)
    response = client.post(
        "/api/library/scan", json={"directory": str(media_dir), "recursive": False}
    )
    assert response.status_code == 200
    task = response.json()
    assert task["task_type"] == "scan"
    assert task["status"] in ("pending", "running", "success")

    # 扫描在后台线程执行，轮询任务状态直至终态
    detail = task
    deadline = time.time() + 30
    while detail["status"] in ("pending", "running") and time.time() < deadline:
        time.sleep(0.2)
        detail = client.get(f"/api/tasks/{task['id']}").json()

    assert detail["status"] == "success"
    assert detail["result"]["added"] >= 1
    assert detail["result"]["failed"] == 0


def test_task_lifecycle(client, sample_items):
    item_id = sample_items[0].id
    created = client.post("/api/tasks/screenshot", json={"media_id": item_id, "at": 1})
    assert created.status_code == 200
    task = created.json()
    assert task["task_type"] == "screenshot"
    assert task["status"] in ("pending", "running", "success", "failed")

    detail = client.get(f"/api/tasks/{task['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == task["id"]

    listing = client.get("/api/tasks").json()
    assert listing["total"] >= 1

    missing = client.get("/api/tasks/999999")
    assert missing.status_code == 404


def test_task_rejects_bad_payload(client):
    assert client.post("/api/tasks/transcode", json={}).status_code == 400
    assert client.post("/api/tasks/screenshot", json={"media_id": 999999}).status_code == 404


def test_stream_range(client, sample_items, tmp_path):
    item = sample_items[0]
    # 用真实文件覆盖路径，使流式接口可读
    payload = b"0123456789" * 100      # 1000 字节
    real_file = tmp_path / "a.mp4"
    real_file.write_bytes(payload)
    item.path = str(real_file)
    from app.database import SessionLocal
    session = SessionLocal()
    session.merge(item)
    session.commit()
    session.close()

    full = client.get(f"/api/stream/{item.id}")
    assert full.status_code == 200
    assert full.content == payload

    partial = client.get(f"/api/stream/{item.id}", headers={"Range": "bytes=0-99"})
    assert partial.status_code == 206
    assert partial.headers["content-range"] == "bytes 0-99/1000"
    assert len(partial.content) == 100

    tail = client.get(f"/api/stream/{item.id}", headers={"Range": "bytes=-50"})
    assert tail.status_code == 206
    assert len(tail.content) == 50

    unsatisfiable = client.get(f"/api/stream/{item.id}", headers={"Range": "bytes=5000-6000"})
    assert unsatisfiable.status_code == 416


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "mediahub" in response.text
