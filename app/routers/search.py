"""关键词搜索与分类聚合（facets）。

与 ``/api/media`` 的区别：``/api/media`` 面向网格分页展示，``/api/search`` 面向
「一次拿到命中列表 + 类型 / 年份聚合面」，便于前端做筛选统计。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Query as SaQuery
from sqlalchemy.orm import Session

from app import models
from app.database import get_db

router = APIRouter(prefix="/api/search", tags=["search"])


def _apply_filters(query: SaQuery, keyword: Optional[str],
                   media_type: Optional[str], year: Optional[int]) -> SaQuery:
    """把搜索条件套用到查询上（供命中列表与聚合面共用）。"""
    if keyword:
        pattern = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                models.MediaItem.title.ilike(pattern),
                models.MediaItem.filename.ilike(pattern),
                models.MediaItem.path.ilike(pattern),
            )
        )
    if media_type:
        query = query.filter(models.MediaItem.media_type == media_type)
    if year:
        query = query.filter(models.MediaItem.year == year)
    return query


@router.get("", summary="关键词搜索 + 类型 / 年份聚合")
def search(
    q: Optional[str] = Query(default=None, description="关键词；留空则返回全部条目"),
    media_type: Optional[str] = Query(default=None, description="video / audio / image"),
    year: Optional[int] = Query(default=None, description="按年份筛选"),
    limit: int = Query(default=50, ge=1, le=200, description="返回条数上限"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    base = _apply_filters(db.query(models.MediaItem), q, media_type, year)
    total = base.count()

    items = (
        base.order_by(models.MediaItem.updated_at.desc(), models.MediaItem.id.desc())
        .limit(limit)
        .all()
    )

    type_rows = (
        _apply_filters(
            db.query(models.MediaItem.media_type, func.count(models.MediaItem.id)), q, media_type, year
        )
        .group_by(models.MediaItem.media_type)
        .all()
    )
    by_type = {str(name or "other"): int(count) for name, count in type_rows}

    year_rows = (
        _apply_filters(
            db.query(models.MediaItem.year, func.count(models.MediaItem.id)), q, media_type, year
        )
        .filter(models.MediaItem.year.isnot(None))
        .group_by(models.MediaItem.year)
        .order_by(models.MediaItem.year.desc())
        .all()
    )
    by_year: List[Dict[str, int]] = [
        {"year": int(value), "count": int(count)} for value, count in year_rows
    ]

    return {
        "query": q or "",
        "total": int(total),
        "returned": len(items),
        "facets": {
            "by_type": {key: by_type.get(key, 0) for key in ("video", "audio", "image", "other")},
            "by_year": by_year,
        },
        "items": [item.to_dict() for item in items],
    }
