"""SQLAlchemy 数据库模型 - 完整 6 表设计"""
import uuid
from datetime import datetime
from typing import List, Optional, AsyncGenerator

from sqlalchemy import (
    Column, String, Text, Integer, Float, Boolean, DateTime, 
    ForeignKey, JSON, Enum as SQLEnum, Index
)
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column
from sqlalchemy.sql import func

from app.config import settings


# ===== Base =====
class Base(DeclarativeBase):
    pass


# ===== UUID helper =====
def generate_uuid() -> str:
    return str(uuid.uuid4())


# ===== Models =====

class WatchlistItem(Base):
    """关注列表 - 股票及其投资论点"""
    __tablename__ = "watchlist_items"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    ticker: Mapped[str] = mapped_column(String(10), unique=True, nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    thesis: Mapped[str] = mapped_column(Text, nullable=True)  # 投资论点
    risk_tags: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)  # List[str] as JSON
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1-5, 1=highest
    sector: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # 板块标签
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    
    # Note: News-Ticker 关系通过 NewsItem.tickers JSON 字段实现
    # 多对多关系表 news_item_tickers 预留给未来扩展


class RawItem(Base):
    """原始数据 - 保留用于复现和调试"""
    __tablename__ = "raw_items"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # finnhub | sec
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # news | filing
    external_id: Mapped[str] = mapped_column(String(200), nullable=True)  # 外部唯一ID
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    raw_payload: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)  # 原始响应
    
    # Relationships
    news_item = relationship("NewsItem", back_populates="raw_item", uselist=False)
    
    __table_args__ = (
        Index("ix_raw_items_source_url", "source", "url"),
    )


class NewsItem(Base):
    """标准化后的新闻条目"""
    __tablename__ = "news_items"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    raw_item_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("raw_items.id"), nullable=True)
    
    canonical_url: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    title_normalized: Mapped[str] = mapped_column(String(500), nullable=True)  # 小写去标点
    content_hash: Mapped[str] = mapped_column(String(64), nullable=True, index=True)  # SHA256
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # finnhub | sec
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # news | filing
    credibility: Mapped[str] = mapped_column(String(10), default="medium")  # high | medium | low
    
    # Ticker 关联 (多对多)
    tickers: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)  # List[str] as JSON
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    
    # Relationships
    raw_item = relationship("RawItem", back_populates="news_item")
    analysis = relationship("AnalysisResult", back_populates="news_item", uselist=False)
    dedup_cluster = relationship("DedupCluster", back_populates="representative_item", uselist=False, 
                                  foreign_keys="DedupCluster.representative_id")
    
    __table_args__ = (
        Index("ix_news_items_source_published", "source", "published_at"),
    )


# Many-to-many association table for NewsItem <-> WatchlistItem
class NewsItemTicker(Base):
    """新闻与股票的多对多关联表"""
    __tablename__ = "news_item_tickers"
    
    news_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("news_items.id"), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), ForeignKey("watchlist_items.ticker"), primary_key=True)


class DedupCluster(Base):
    """去重聚类 - 记录去重结果和原因"""
    __tablename__ = "dedup_clusters"
    
    cluster_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    representative_id: Mapped[str] = mapped_column(String(36), ForeignKey("news_items.id"), nullable=False)
    member_ids: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)  # List[str] 被合并的条目
    dedup_method: Mapped[str] = mapped_column(String(20), nullable=False)  # url_exact | hash_match | similarity
    similarity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 如果是相似度去重
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    
    # Relationships
    representative_item = relationship("NewsItem", back_populates="dedup_cluster", 
                                        foreign_keys=[representative_id])


class AnalysisResult(Base):
    """AI 分析结果 - 可回放，记录 prompt 版本和模型"""
    __tablename__ = "analysis_results"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    news_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("news_items.id"), nullable=False, unique=True)
    
    # AI 模型信息（用于回放）
    provider: Mapped[str] = mapped_column(String(20), nullable=False)  # gemini | openai | claude
    model: Mapped[str] = mapped_column(String(50), nullable=False)  # gemini-pro | gpt-4o-mini
    prompt_version: Mapped[str] = mapped_column(String(20), default="v1.0")  # 用于追踪 prompt 变化
    
    # 结构化输出（严格 Schema）
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)  # earnings | regulatory | product | ...
    impact_direction: Mapped[str] = mapped_column(String(10), nullable=False)  # bullish | bearish | neutral
    impact_horizon: Mapped[str] = mapped_column(String(10), nullable=False)  # short | medium | long
    thesis_relation: Mapped[str] = mapped_column(String(15), nullable=False)  # supports | weakens | unrelated
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)  # high | medium | low
    confidence_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    summary: Mapped[str] = mapped_column(String(200), nullable=False)  # AI 生成的摘要
    key_facts: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)  # List[str] <= 3 条
    watch_next: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # 下一催化剂
    
    # 成本追踪
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    
    # Relationships
    news_item = relationship("NewsItem", back_populates="analysis")
    
    __table_args__ = (
        Index("ix_analysis_results_event_impact", "event_type", "impact_direction"),
    )


class PipelineRun(Base):
    """流水线运行记录 - 可观测性"""
    __tablename__ = "pipeline_runs"
    
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | success | partial | failed
    
    # 统计
    raw_collected: Mapped[int] = mapped_column(Integer, default=0)
    after_normalize: Mapped[int] = mapped_column(Integer, default=0)
    after_dedup: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_success: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_failed: Mapped[int] = mapped_column(Integer, default=0)
    delivered: Mapped[int] = mapped_column(Integer, default=0)
    
    error_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Relationships
    delivery_logs = relationship("DeliveryLog", back_populates="pipeline_run")


class DeliveryLog(Base):
    """推送日志"""
    __tablename__ = "delivery_logs"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("pipeline_runs.run_id"), nullable=False)
    
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # notion | email | telegram
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | success | failed | retrying
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Channel-specific data
    notion_page_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    pipeline_run = relationship("PipelineRun", back_populates="delivery_logs")


# ===== Database Engine & Session =====

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """初始化数据库表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话（用于依赖注入）"""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_db() -> None:
    """关闭数据库连接池"""
    await engine.dispose()
