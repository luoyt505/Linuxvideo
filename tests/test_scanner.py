"""扫描服务单元测试。"""
from __future__ import annotations

from pathlib import Path

from app import models
from app.services import scanner
from app.utils import ffmpeg_utils


def _write(directory: Path, name: str, size: int = 2048) -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)
    return path


def test_scan_indexes_media_files(db, media_dir):  # noqa: WPS442
    _write(media_dir, "movie_one.mp4")
    _write(media_dir, "song_two.mp3")
    _write(media_dir, "poster.jpg")
    _write(media_dir, "notes.txt")            # 非媒体文件，应被忽略

    stats = scanner.scan_directory(
        db, directory=str(media_dir), recursive=False
    )

    assert stats["total"] == 3
    assert stats["added"] == 3
    assert stats["failed"] == 0

    items = db.query(models.MediaItem).all()
    names = {item.filename for item in items}
    assert names == {"movie_one.mp4", "song_two.mp3", "poster.jpg"}
    assert all(item.media_type in ("video", "audio", "image") for item in items)


def test_scan_is_idempotent(db, media_dir):
    _write(media_dir, "repeat.mp4")

    first = scanner.scan_directory(db, directory=str(media_dir))
    second = scanner.scan_directory(db, directory=str(media_dir))

    assert first["added"] == 1
    assert second["added"] == 0
    assert second["skipped"] == 1
    assert db.query(models.MediaItem).count() == 1


def test_scan_detects_change_by_mtime(db, media_dir):
    path = _write(media_dir, "changing.mp4", size=1024)
    scanner.scan_directory(db, directory=str(media_dir))

    # 修改文件内容与时间戳
    path.write_bytes(b"\x01" * 4096)
    stats = scanner.scan_directory(db, directory=str(media_dir))

    assert stats["updated"] == 1
    item = db.query(models.MediaItem).one()
    assert item.size == 4096


def test_scan_removes_missing_entries(db, media_dir):
    path = _write(media_dir, "gone.mp4")
    scanner.scan_directory(db, directory=str(media_dir))
    assert db.query(models.MediaItem).count() == 1

    path.unlink()
    stats = scanner.scan_directory(db, directory=str(media_dir))

    assert stats["removed"] == 1
    assert db.query(models.MediaItem).count() == 0


def test_scan_recursive_mode(db, media_dir):
    _write(media_dir, "top.mp4")
    _write(media_dir, "nested/deep.mp4")

    flat = scanner.scan_directory(db, directory=str(media_dir), recursive=False)
    assert flat["total"] == 1

    deep = scanner.scan_directory(db, directory=str(media_dir), recursive=True)
    assert deep["total"] == 2          # top.mp4 + nested/deep.mp4
    assert deep["added"] == 1          # top.mp4 已入库，本轮仅新增深层文件
    assert db.query(models.MediaItem).count() == 2


def test_scan_records_directories(db, media_dir):
    _write(media_dir, "clip.mkv")
    stats = scanner.scan_directory(db, directory=str(media_dir))
    assert stats["directories"] == [str(media_dir)]


def test_classify_helper():
    assert ffmpeg_utils.classify(Path("a.mp4")) == "video"
    assert ffmpeg_utils.classify(Path("a.mp3")) == "audio"
    assert ffmpeg_utils.classify(Path("a.png")) == "image"
    assert ffmpeg_utils.classify(Path("a.txt")) is None
