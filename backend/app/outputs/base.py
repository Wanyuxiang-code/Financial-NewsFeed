"""输出处理器抽象基类"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict
from dataclasses import dataclass, field
from datetime import datetime

from app.models.schemas import NewsItemCreate, AIAnalysisOutput
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DigestItem:
    """摘要中的单个新闻条目"""
    news: NewsItemCreate
    analysis: Optional[AIAnalysisOutput]
    
    @property
    def is_analyzed(self) -> bool:
        return self.analysis is not None


@dataclass
class TickerSummary:
    """单只股票的每日汇总分析"""
    ticker: str
    company_name: str
    news_count: int
    
    # AI 生成的汇总
    overall_sentiment: str  # bullish / bearish / neutral / mixed
    summary: str  # 1-2 句话总结
    key_events: List[str]  # 关键事件（最多 3 条）
    thesis_impact: str  # 对投资论点的影响
    action_suggestion: str  # 行动建议
    risk_alerts: List[str]  # 风险提示
    
    # 统计
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0


@dataclass
class Digest:
    """每日摘要"""
    run_id: str
    generated_at: datetime
    window_start: datetime
    window_end: datetime
    items: List[DigestItem]
    
    # 统计
    total_collected: int = 0
    total_after_dedup: int = 0
    total_analyzed: int = 0
    total_failed: int = 0
    
    # 每只股票的汇总分析
    ticker_summaries: Dict[str, TickerSummary] = field(default_factory=dict)
    
    @property
    def high_impact_items(self) -> List[DigestItem]:
        """返回高影响力条目（利多或利空）"""
        return [
            item for item in self.items
            if item.analysis and item.analysis.impact_direction != "neutral"
        ]
    
    @property
    def by_ticker(self) -> dict:
        """按 ticker 分组"""
        result = {}
        for item in self.items:
            if item.news.tickers:
                for ticker in item.news.tickers:
                    if ticker not in result:
                        result[ticker] = []
                    result[ticker].append(item)
        return result


class OutputError(Exception):
    """输出错误"""
    pass


class BaseOutput(ABC):
    """
    输出处理器抽象基类
    
    所有输出处理器必须实现:
    - deliver(): 发送摘要
    - name: 输出渠道名称
    """
    
    name: str = "base"
    
    @abstractmethod
    async def deliver(self, digest: Digest) -> str:
        """
        发送摘要
        
        Args:
            digest: 每日摘要
        
        Returns:
            输出标识（如 Notion page ID, 邮件 ID 等）
        
        Raises:
            OutputError: 发送失败
        """
        pass
    
    async def close(self):
        """关闭资源（子类可重写）"""
        pass
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
