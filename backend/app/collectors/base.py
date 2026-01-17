"""数据采集器抽象基类"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional, Literal
from dataclasses import dataclass, field

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RawNewsData:
    """
    采集器返回的原始数据结构
    
    与数据库 RawItem 对应，但是纯数据类
    """
    source: str  # finnhub | sec
    source_type: str  # news | filing
    external_id: Optional[str] = None
    url: str = ""
    title: str = ""
    summary: Optional[str] = None
    published_at: Optional[datetime] = None
    tickers: List[str] = field(default_factory=list)
    raw_payload: Optional[dict] = None
    
    # 额外元数据
    author: Optional[str] = None
    category: Optional[str] = None
    image_url: Optional[str] = None


class BaseCollector(ABC):
    """
    数据采集器抽象基类
    
    所有采集器必须实现:
    - collect(): 采集数据
    - source: 数据源名称
    - source_type: 数据类型 (news/filing)
    - credibility: 可信度
    """
    
    # 子类必须设置这些属性
    source: str = "unknown"
    source_type: Literal["news", "filing"] = "news"
    credibility: Literal["high", "medium", "low"] = "medium"
    
    @abstractmethod
    async def collect(
        self,
        tickers: List[str],
        since: datetime,
        until: Optional[datetime] = None
    ) -> List[RawNewsData]:
        """
        采集新闻/公告数据
        
        Args:
            tickers: 股票代码列表
            since: 开始时间
            until: 结束时间（可选，默认到现在）
        
        Returns:
            原始新闻数据列表
        """
        pass
    
    async def collect_single(
        self,
        ticker: str,
        since: datetime,
        until: Optional[datetime] = None
    ) -> List[RawNewsData]:
        """
        采集单个股票的新闻（默认实现调用 collect）
        """
        return await self.collect([ticker], since, until)
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(source={self.source}, type={self.source_type}, credibility={self.credibility})"
