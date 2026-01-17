"""CRUD 操作 - 数据库增删改查"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, update, delete, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.database import (
    WatchlistItem, RawItem, NewsItem, DedupCluster,
    AnalysisResult, PipelineRun, DeliveryLog
)
from app.models.schemas import (
    WatchlistItemCreate, WatchlistItemUpdate,
    RawItemCreate, NewsItemCreate, AnalysisResultCreate,
    DedupClusterCreate, PipelineRunCreate, PipelineRunUpdate,
    DeliveryLogCreate, DeliveryLogUpdate
)


# ===== Watchlist CRUD =====

async def get_watchlist(
    db: AsyncSession,
    sector: Optional[str] = None,
    priority: Optional[int] = None
) -> List[WatchlistItem]:
    """获取关注列表"""
    query = select(WatchlistItem)
    if sector:
        query = query.where(WatchlistItem.sector == sector)
    if priority:
        query = query.where(WatchlistItem.priority == priority)
    query = query.order_by(WatchlistItem.priority, WatchlistItem.ticker)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_watchlist_item(db: AsyncSession, ticker: str) -> Optional[WatchlistItem]:
    """获取单个股票"""
    query = select(WatchlistItem).where(WatchlistItem.ticker == ticker)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create_watchlist_item(db: AsyncSession, item: WatchlistItemCreate) -> WatchlistItem:
    """创建关注列表条目"""
    db_item = WatchlistItem(
        ticker=item.ticker.upper(),
        company_name=item.company_name,
        thesis=item.thesis,
        risk_tags=item.risk_tags,
        priority=item.priority,
        sector=item.sector,
    )
    db.add(db_item)
    await db.flush()
    await db.refresh(db_item)
    return db_item


async def update_watchlist_item(
    db: AsyncSession,
    ticker: str,
    item: WatchlistItemUpdate
) -> Optional[WatchlistItem]:
    """更新关注列表条目"""
    db_item = await get_watchlist_item(db, ticker)
    if not db_item:
        return None
    
    update_data = item.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_item, field, value)
    
    await db.flush()
    await db.refresh(db_item)
    return db_item


async def delete_watchlist_item(db: AsyncSession, ticker: str) -> bool:
    """删除关注列表条目"""
    result = await db.execute(
        delete(WatchlistItem).where(WatchlistItem.ticker == ticker)
    )
    return result.rowcount > 0


# ===== Raw Item CRUD =====

async def create_raw_item(db: AsyncSession, item: RawItemCreate) -> RawItem:
    """创建原始数据条目"""
    db_item = RawItem(**item.model_dump())
    db.add(db_item)
    await db.flush()
    await db.refresh(db_item)
    return db_item


async def get_raw_item_by_url(db: AsyncSession, source: str, url: str) -> Optional[RawItem]:
    """通过 URL 查找原始数据（用于去重）"""
    query = select(RawItem).where(
        and_(RawItem.source == source, RawItem.url == url)
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


# ===== News Item CRUD =====

async def create_news_item(db: AsyncSession, item: NewsItemCreate) -> NewsItem:
    """创建新闻条目"""
    db_item = NewsItem(**item.model_dump())
    db.add(db_item)
    await db.flush()
    await db.refresh(db_item)
    return db_item


async def get_news_item_by_id(db: AsyncSession, news_id: UUID) -> Optional[NewsItem]:
    """通过 ID 获取新闻条目"""
    query = select(NewsItem).where(NewsItem.id == str(news_id)).options(
        selectinload(NewsItem.analysis)
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_news_item_by_hash(db: AsyncSession, content_hash: str) -> Optional[NewsItem]:
    """通过内容哈希查找新闻（用于去重）"""
    query = select(NewsItem).where(NewsItem.content_hash == content_hash)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_news_item_by_url(db: AsyncSession, canonical_url: str) -> Optional[NewsItem]:
    """通过规范化 URL 查找新闻（用于去重）"""
    query = select(NewsItem).where(NewsItem.canonical_url == canonical_url)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_news_items(
    db: AsyncSession,
    ticker: Optional[str] = None,
    source: Optional[str] = None,
    source_type: Optional[str] = None,
    event_type: Optional[str] = None,
    impact_direction: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0
) -> List[NewsItem]:
    """查询新闻条目，支持多种过滤"""
    query = select(NewsItem).options(selectinload(NewsItem.analysis))
    
    conditions = []
    if ticker:
        # JSON 包含查询 (SQLite 兼容)
        conditions.append(NewsItem.tickers.contains(ticker))
    if source:
        conditions.append(NewsItem.source == source)
    if source_type:
        conditions.append(NewsItem.source_type == source_type)
    if since:
        conditions.append(NewsItem.published_at >= since)
    if until:
        conditions.append(NewsItem.published_at <= until)
    
    if conditions:
        query = query.where(and_(*conditions))
    
    # 如果需要按分析结果过滤，需要 join
    if event_type or impact_direction:
        query = query.join(AnalysisResult)
        if event_type:
            query = query.where(AnalysisResult.event_type == event_type)
        if impact_direction:
            query = query.where(AnalysisResult.impact_direction == impact_direction)
    
    query = query.order_by(NewsItem.published_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


# ===== Analysis Result CRUD =====

async def create_analysis_result(db: AsyncSession, item: AnalysisResultCreate) -> AnalysisResult:
    """创建分析结果"""
    db_item = AnalysisResult(**item.model_dump())
    db.add(db_item)
    await db.flush()
    await db.refresh(db_item)
    return db_item


async def get_analysis_by_news_id(db: AsyncSession, news_id: UUID) -> Optional[AnalysisResult]:
    """通过新闻 ID 获取分析结果"""
    query = select(AnalysisResult).where(AnalysisResult.news_item_id == str(news_id))
    result = await db.execute(query)
    return result.scalar_one_or_none()


# ===== Dedup Cluster CRUD =====

async def create_dedup_cluster(db: AsyncSession, item: DedupClusterCreate) -> DedupCluster:
    """创建去重聚类"""
    db_item = DedupCluster(**item.model_dump())
    db.add(db_item)
    await db.flush()
    await db.refresh(db_item)
    return db_item


# ===== Pipeline Run CRUD =====

async def create_pipeline_run(db: AsyncSession, item: PipelineRunCreate) -> PipelineRun:
    """创建流水线运行记录"""
    db_item = PipelineRun(
        run_id=str(item.run_id),
        status=item.status,
        started_at=item.started_at
    )
    db.add(db_item)
    await db.flush()
    await db.refresh(db_item)
    return db_item


async def get_pipeline_run(db: AsyncSession, run_id: UUID) -> Optional[PipelineRun]:
    """获取流水线运行记录"""
    query = select(PipelineRun).where(PipelineRun.run_id == str(run_id))
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def update_pipeline_run(
    db: AsyncSession,
    run_id: UUID,
    update_data: PipelineRunUpdate
) -> Optional[PipelineRun]:
    """更新流水线运行记录"""
    db_item = await get_pipeline_run(db, run_id)
    if not db_item:
        return None
    
    for field, value in update_data.model_dump(exclude_unset=True).items():
        setattr(db_item, field, value)
    
    await db.flush()
    await db.refresh(db_item)
    return db_item


async def get_pipeline_runs(
    db: AsyncSession,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0
) -> List[PipelineRun]:
    """获取流水线运行历史"""
    query = select(PipelineRun)
    if status:
        query = query.where(PipelineRun.status == status)
    query = query.order_by(PipelineRun.started_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


# ===== Delivery Log CRUD =====

async def create_delivery_log(db: AsyncSession, item: DeliveryLogCreate) -> DeliveryLog:
    """创建推送日志"""
    db_item = DeliveryLog(**item.model_dump())
    db.add(db_item)
    await db.flush()
    await db.refresh(db_item)
    return db_item


async def update_delivery_log(
    db: AsyncSession,
    log_id: str,
    update_data: DeliveryLogUpdate
) -> Optional[DeliveryLog]:
    """更新推送日志"""
    query = select(DeliveryLog).where(DeliveryLog.id == log_id)
    result = await db.execute(query)
    db_item = result.scalar_one_or_none()
    
    if not db_item:
        return None
    
    for field, value in update_data.model_dump(exclude_unset=True).items():
        setattr(db_item, field, value)
    
    await db.flush()
    await db.refresh(db_item)
    return db_item
