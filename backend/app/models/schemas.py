"""Pydantic Schemas - API 请求/响应模型 + AI 输出严格 Schema"""
from datetime import datetime
from typing import List, Optional, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ===== AI Analysis Output Schema (严格结构) =====

class AIAnalysisOutput(BaseModel):
    """AI 必须输出的严格结构 - 用于 JSON 校验"""
    
    event_type: Literal[
        "earnings", "guidance", "regulatory", "contract",
        "product", "accident", "macro", "rumor", "other"
    ]
    impact_direction: Literal["bullish", "bearish", "neutral"]
    impact_horizon: Literal["short", "medium", "long"]
    thesis_relation: Literal["supports", "weakens", "unrelated"]
    confidence: Literal["high", "medium", "low"]
    confidence_reason: str = Field(max_length=100)
    summary: str = Field(max_length=100)
    key_facts: List[str] = Field(max_length=3, default_factory=list)
    watch_next: str = Field(max_length=50, default="")
    
    @field_validator('key_facts', mode='before')
    @classmethod
    def validate_key_facts(cls, v):
        if v is None:
            return []
        # 截断每个 fact 到 200 字符，最多 3 条
        return [str(f)[:200] for f in v[:3]]
    
    @field_validator('summary', mode='before')
    @classmethod
    def validate_summary(cls, v):
        return str(v)[:100] if v else ""
    
    @field_validator('confidence_reason', mode='before')
    @classmethod
    def validate_confidence_reason(cls, v):
        return str(v)[:100] if v else ""
    
    @field_validator('watch_next', mode='before')
    @classmethod
    def validate_watch_next(cls, v):
        return str(v)[:50] if v else ""


# ===== Watchlist Schemas =====

class WatchlistItemBase(BaseModel):
    """关注列表基础字段"""
    ticker: str = Field(max_length=10)
    company_name: str = Field(max_length=200)
    thesis: Optional[str] = None
    risk_tags: Optional[List[str]] = None
    priority: int = Field(default=3, ge=1, le=5)
    sector: Optional[str] = Field(default=None, max_length=50)
    
    @field_validator('ticker', mode='before')
    @classmethod
    def uppercase_ticker(cls, v):
        return v.upper() if v else v


class WatchlistItemCreate(WatchlistItemBase):
    """创建关注列表条目"""
    pass


class WatchlistItemUpdate(BaseModel):
    """更新关注列表条目（所有字段可选）"""
    company_name: Optional[str] = Field(default=None, max_length=200)
    thesis: Optional[str] = None
    risk_tags: Optional[List[str]] = None
    priority: Optional[int] = Field(default=None, ge=1, le=5)
    sector: Optional[str] = Field(default=None, max_length=50)


class WatchlistItemResponse(WatchlistItemBase):
    """关注列表响应"""
    id: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# ===== Raw Item Schemas =====

class RawItemBase(BaseModel):
    """原始数据基础字段"""
    source: str
    source_type: str
    external_id: Optional[str] = None
    url: str
    raw_payload: Optional[dict] = None


class RawItemCreate(RawItemBase):
    """创建原始数据条目"""
    pass


class RawItemResponse(RawItemBase):
    """原始数据响应"""
    id: str
    fetched_at: datetime
    
    class Config:
        from_attributes = True


# ===== News Item Schemas =====

class NewsItemBase(BaseModel):
    """新闻条目基础字段"""
    canonical_url: str
    title: str
    summary: Optional[str] = None
    published_at: datetime
    source: str
    source_type: str
    credibility: str = "medium"
    tickers: Optional[List[str]] = None


class NewsItemCreate(NewsItemBase):
    """创建新闻条目"""
    title_normalized: Optional[str] = None
    content_hash: Optional[str] = None
    raw_item_id: Optional[str] = None


class NewsItemResponse(NewsItemBase):
    """新闻条目响应（包含分析结果）"""
    id: str
    title_normalized: Optional[str] = None
    content_hash: Optional[str] = None
    created_at: datetime
    analysis: Optional["AnalysisResultResponse"] = None
    
    class Config:
        from_attributes = True


# ===== Analysis Result Schemas =====

class AnalysisResultBase(BaseModel):
    """分析结果基础字段"""
    provider: str
    model: str
    prompt_version: str = "v1.0"
    event_type: str
    impact_direction: str
    impact_horizon: str
    thesis_relation: str
    confidence: str
    confidence_reason: Optional[str] = None
    summary: str
    key_facts: Optional[List[str]] = None
    watch_next: Optional[str] = None
    tokens_used: Optional[int] = None
    cost_usd: Optional[float] = None


class AnalysisResultCreate(AnalysisResultBase):
    """创建分析结果"""
    news_item_id: str


class AnalysisResultResponse(AnalysisResultBase):
    """分析结果响应"""
    id: str
    news_item_id: str
    created_at: datetime
    
    class Config:
        from_attributes = True


# ===== Dedup Cluster Schemas =====

class DedupClusterCreate(BaseModel):
    """创建去重聚类"""
    representative_id: str
    member_ids: Optional[List[str]] = None
    dedup_method: str
    similarity_score: Optional[float] = None


class DedupClusterResponse(BaseModel):
    """去重聚类响应"""
    cluster_id: str
    representative_id: str
    member_ids: Optional[List[str]] = None
    dedup_method: str
    similarity_score: Optional[float] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


# ===== Pipeline Run Schemas =====

class PipelineRunCreate(BaseModel):
    """创建流水线运行记录"""
    run_id: UUID
    status: str = "running"
    started_at: datetime


class PipelineRunUpdate(BaseModel):
    """更新流水线运行记录"""
    finished_at: Optional[datetime] = None
    status: Optional[str] = None
    raw_collected: Optional[int] = None
    after_normalize: Optional[int] = None
    after_dedup: Optional[int] = None
    analyzed_success: Optional[int] = None
    analyzed_failed: Optional[int] = None
    delivered: Optional[int] = None
    error_log: Optional[str] = None


class PipelineRunResponse(BaseModel):
    """流水线运行响应"""
    run_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: str
    raw_collected: int = 0
    after_normalize: int = 0
    after_dedup: int = 0
    analyzed_success: int = 0
    analyzed_failed: int = 0
    delivered: int = 0
    error_log: Optional[str] = None
    
    class Config:
        from_attributes = True


# ===== Delivery Log Schemas =====

class DeliveryLogCreate(BaseModel):
    """创建推送日志"""
    run_id: str
    channel: str
    status: str = "pending"


class DeliveryLogUpdate(BaseModel):
    """更新推送日志"""
    status: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: Optional[int] = None
    notion_page_id: Optional[str] = None


class DeliveryLogResponse(BaseModel):
    """推送日志响应"""
    id: str
    run_id: str
    channel: str
    status: str
    error_message: Optional[str] = None
    retry_count: int = 0
    notion_page_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# Update forward references
NewsItemResponse.model_rebuild()
