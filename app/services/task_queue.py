"""后台任务队列与执行器。

基于线程池（``queue.Queue`` + 工作线程）实现，任务状态持久化到数据库，
支持进度上报与取消。

任务类型：
- ``scan``           扫描媒体目录
- ``transcode``      转码
- ``extract_audio``  抽音轨
- ``screenshot``     截图
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.database import SessionLocal
from app.services import scanner
from app.utils import ffmpeg_utils
from app.utils.ffmpeg_utils import TaskCancelled

logger = logging.getLogger(__name__)

ProgressCb = Callable[[int], None]
CancelCb = Callable[[], bool]


# --------------------------------------------------------------------------- #
# 任务处理器
# --------------------------------------------------------------------------- #
def handle_scan(db: Session, task: models.Task, params: Dict[str, Any],
                progress_cb: ProgressCb, cancel_cb: CancelCb) -> Dict[str, Any]:
    return scanner.scan_directory(
        db,
        directory=params.get("directory"),
        recursive=params.get("recursive"),
        on_progress=progress_cb,
        cancel_check=cancel_cb,
    )


def handle_transcode(db: Session, task: models.Task, params: Dict[str, Any],
                     progress_cb: ProgressCb, cancel_cb: CancelCb) -> Dict[str, Any]:
    source = Path(params["source_path"])
    dest = Path(params["output_path"])
    ffmpeg_utils.transcode(
        source,
        dest,
        vcodec=params.get("vcodec", "libx264"),
        acodec=params.get("acodec", "aac"),
        crf=params.get("crf"),
        preset=params.get("preset"),
        scale=params.get("scale"),
        audio_bitrate=params.get("audio_bitrate", "192k"),
        duration=float(params.get("duration") or 0.0),
        on_progress=progress_cb,
        cancel_check=cancel_cb,
    )
    return {"output_path": str(dest), "size": dest.stat().st_size if dest.exists() else 0}


def handle_extract_audio(db: Session, task: models.Task, params: Dict[str, Any],
                         progress_cb: ProgressCb, cancel_cb: CancelCb) -> Dict[str, Any]:
    source = Path(params["source_path"])
    dest = Path(params["output_path"])
    ffmpeg_utils.extract_audio(
        source,
        dest,
        acodec=params.get("acodec", "libmp3lame"),
        bitrate=params.get("bitrate", "192k"),
        duration=float(params.get("duration") or 0.0),
        on_progress=progress_cb,
        cancel_check=cancel_cb,
    )
    return {"output_path": str(dest), "size": dest.stat().st_size if dest.exists() else 0}


def handle_screenshot(db: Session, task: models.Task, params: Dict[str, Any],
                      progress_cb: ProgressCb, cancel_cb: CancelCb) -> Dict[str, Any]:
    source = Path(params["source_path"])
    dest = Path(params["output_path"])
    progress_cb(10)
    ffmpeg_utils.capture_frame(source, dest, at=float(params.get("at") or 0.0),
                               width=params.get("width"))
    progress_cb(100)
    return {"output_path": str(dest), "size": dest.stat().st_size if dest.exists() else 0}


HANDLERS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "scan": handle_scan,
    "transcode": handle_transcode,
    "extract_audio": handle_extract_audio,
    "screenshot": handle_screenshot,
}


# --------------------------------------------------------------------------- #
# 队列
# --------------------------------------------------------------------------- #
class TaskQueue:
    """基于工作线程的后台任务队列。"""

    def __init__(self, workers: int = 2) -> None:
        self.workers = max(1, int(workers))
        self._queue: "queue.Queue[Optional[int]]" = queue.Queue()
        self._threads: list = []
        self._cancel_flags: Dict[int, bool] = {}
        self._lock = threading.Lock()
        self._started = False

    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for index in range(self.workers):
            thread = threading.Thread(
                target=self._loop, name=f"mediahub-worker-{index}", daemon=True
            )
            thread.start()
            self._threads.append(thread)
        logger.info("任务队列已启动，工作线程数：%s", self.workers)

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        for _ in self._threads:
            self._queue.put(None)
        self._threads.clear()
        logger.info("任务队列已停止")

    # ------------------------------------------------------------------ #
    def enqueue(self, db: Session, task_type: str, params: Optional[Dict[str, Any]] = None,
                source_path: Optional[str] = None,
                output_path: Optional[str] = None) -> models.Task:
        """创建任务记录并入队。"""
        if task_type not in HANDLERS:
            raise ValueError(f"未知任务类型：{task_type}")
        task = models.Task(
            task_type=task_type,
            status="pending",
            progress=0,
            params=json.dumps(params or {}, ensure_ascii=False),
            source_path=source_path,
            output_path=output_path,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        self.submit(task.id)
        return task

    def submit(self, task_id: int) -> None:
        self._queue.put(task_id)

    def cancel(self, task_id: int) -> None:
        """标记任务取消；运行中的任务会在下一次进度检查时终止。"""
        with self._lock:
            self._cancel_flags[int(task_id)] = True

    def is_cancelled(self, task_id: int) -> bool:
        with self._lock:
            return bool(self._cancel_flags.get(int(task_id)))

    def pending_count(self) -> int:
        return self._queue.qsize()

    @property
    def worker_count(self) -> int:
        return self.workers

    # ------------------------------------------------------------------ #
    def _loop(self) -> None:
        while True:
            task_id = self._queue.get()
            if task_id is None:
                self._queue.task_done()
                break
            try:
                self._run_task(int(task_id))
            except Exception:  # noqa: BLE001 - 保证工作线程不因单任务崩溃
                logger.exception("任务 %s 执行异常", task_id)
            finally:
                self._queue.task_done()

    def _run_task(self, task_id: int) -> None:
        db = SessionLocal()
        try:
            task = db.get(models.Task, task_id)
            if task is None:
                return

            if self.is_cancelled(task_id) or task.status == "canceled":
                task.status = "canceled"
                task.finished_at = datetime.utcnow()
                db.commit()
                return

            task.status = "running"
            task.started_at = datetime.utcnow()
            task.progress = max(1, int(task.progress or 0))
            db.commit()

            params: Dict[str, Any] = {}
            if task.params:
                try:
                    params = json.loads(task.params)
                except (TypeError, ValueError):
                    params = {}

            def progress_cb(value: int) -> None:
                try:
                    task.progress = max(0, min(100, int(value)))
                    db.commit()
                except Exception:  # noqa: BLE001
                    db.rollback()

            def cancel_cb() -> bool:
                return self.is_cancelled(task_id)

            handler = HANDLERS[task.task_type]
            result = handler(db, task, params, progress_cb, cancel_cb)

            task.result = json.dumps(result or {}, ensure_ascii=False)
            task.progress = 100
            task.status = "success"
            task.finished_at = datetime.utcnow()
            if isinstance(result, dict) and result.get("output_path"):
                task.output_path = str(result["output_path"])
            db.commit()
            logger.info("任务 %s（%s）执行成功", task_id, task.task_type)

        except TaskCancelled:
            db.rollback()
            task = db.get(models.Task, task_id)
            if task is not None:
                task.status = "canceled"
                task.finished_at = datetime.utcnow()
                db.commit()
            logger.info("任务 %s 已取消", task_id)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            task = db.get(models.Task, task_id)
            if task is not None:
                task.status = "failed"
                task.error = str(exc)
                task.finished_at = datetime.utcnow()
                db.commit()
            logger.error("任务 %s 失败：%s", task_id, exc)
        finally:
            db.close()


# 全局单例
task_queue = TaskQueue(workers=settings.worker_count)
