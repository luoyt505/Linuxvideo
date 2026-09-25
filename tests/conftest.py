"""共享测试夹具。

测试使用独立的临时数据库与临时媒体目录，避免污染真实数据。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 在导入 app 之前设定环境变量，确保使用临时数据库 / 目录
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="mediahub-test-"))
os.environ.setdefault("DATA_DIR", str(_TMP_ROOT / "data"))
os.environ.setdefault("CACHE_DIR", str(_TMP_ROOT / "data" / "cache"))
os.environ.setdefault("TRANSCODE_DIR", str(_TMP_ROOT / "data" / "transcoded"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TMP_ROOT / 'data' / 'test.db').as_posix()}")
os.environ.setdefault("MEDIA_DIRS", str(_TMP_ROOT / "media"))
os.environ.setdefault("SCAN_THUMBNAILS", "false")
os.environ.setdefault("WORKER_COUNT", "1")

from app import models  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _prepare_dirs():
    settings.ensure_dirs()
    (_TMP_ROOT / "media").mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture()
def db():
    """每个用例一个干净的表结构与数据库会话。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def media_dir():
    """独立的媒体目录，用例结束后清理创建的文件。"""
    directory = _TMP_ROOT / "media" / "case"
    directory.mkdir(parents=True, exist_ok=True)
    yield directory
    for child in directory.rglob("*"):
        try:
            if child.is_file():
                child.unlink()
        except OSError:
            pass


@pytest.fixture()
def sample_items(db):
    """预置若干媒体条目。"""
    media_root = _TMP_ROOT / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    # 落盘真实占位文件，保证下载 / 流式播放 / 截图等依赖文件系统的用例可用
    for name in ("a.mp4", "b.mp3", "c.jpg"):
        (media_root / name).write_bytes(b"\x00" * 4096)

    rows = [
        models.MediaItem(
            path=str(_TMP_ROOT / "media" / "a.mp4"), filename="a.mp4", title="演示视频 A",
            media_type="video", container="mp4", size=1024 * 1024, duration=120.5,
            width=1920, height=1080, video_codec="h264", audio_codec="aac",
            bit_rate=1500000, frame_rate=29.97, stream_count=2, year=2024,
            directory=str(_TMP_ROOT / "media"), mtime=1700000000.0,
        ),
        models.MediaItem(
            path=str(_TMP_ROOT / "media" / "b.mp3"), filename="b.mp3", title="演示音频 B",
            media_type="audio", container="mp3", size=512 * 1024, duration=210.0,
            audio_codec="mp3", sample_rate=44100, channels=2, bit_rate=320000,
            stream_count=1, year=2023, directory=str(_TMP_ROOT / "media"), mtime=1700000001.0,
        ),
        models.MediaItem(
            path=str(_TMP_ROOT / "media" / "c.jpg"), filename="c.jpg", title="演示图片 C",
            media_type="image", container="jpeg", size=256 * 1024, duration=0.0,
            width=800, height=600, stream_count=1, year=2024,
            directory=str(_TMP_ROOT / "media"), mtime=1700000002.0,
        ),
    ]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows
