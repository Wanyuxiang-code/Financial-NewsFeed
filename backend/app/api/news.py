"""News API endpoints - query historical news and analysis"""
from typing import List, Optional
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.schemas import NewsItemResponse, AnalysisResultResponse
from app.models import crud

router = APIRouter()


@router.get("", response_model=List[NewsItemResponse])
async def get_news(
    ticker: Optional[str] = None,
    source: Optional[str] = None,
    source_type: Optional[str] = None,
    event_type: Optional[str] = None,
    impact_direction: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    """
    查询历史新闻，支持多种过滤条件
    
    - ticker: 股票代码
    - source: 数据源 (finnhub, sec)
    - source_type: 类型 (news, filing)
    - event_type: 事件类型 (earnings, regulatory, product, etc.)
    - impact_direction: 影响方向 (bullish, bearish, neutral)
    - since/until: 时间范围
    """
    items = await crud.get_news_items(
        db,
        ticker=ticker.upper() if ticker else None,
        source=source,
        source_type=source_type,
        event_type=event_type,
        impact_direction=impact_direction,
        since=since,
        until=until,
        limit=limit,
        offset=offset
    )
    return items


@router.get("/{news_id}", response_model=NewsItemResponse)
async def get_news_item(news_id: UUID, db: AsyncSession = Depends(get_db)):
    """获取单条新闻详情，包含 AI 分析结果"""
    item = await crud.get_news_item_by_id(db, news_id=news_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"News item {news_id} not found")
    return item


@router.get("/{news_id}/analysis", response_model=AnalysisResultResponse)
async def get_news_analysis(news_id: UUID, db: AsyncSession = Depends(get_db)):
    """获取单条新闻的 AI 分析结果"""
    analysis = await crud.get_analysis_by_news_id(db, news_id=news_id)
    if not analysis:
        raise HTTPException(status_code=404, detail=f"Analysis for news {news_id} not found")
    return analysis
