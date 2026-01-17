"""数据标准化器 - 将原始数据转换为标准化的 NewsItem"""
from datetime import datetime
from typing import List, Optional, Tuple
import hashlib

from app.collectors.base import RawNewsData
from app.models.schemas import NewsItemCreate, RawItemCreate
from app.utils.deduplicator import Deduplicator
from app.utils.logger import get_logger

logger = get_logger(__name__)


class Normalizer:
    """
    数据标准化器
    
    职责:
    1. 将 RawNewsData 转换为数据库模型
    2. 计算规范化字段（URL、标题、内容哈希）
    3. 根据来源确定可信度
    """
    
    # 来源可信度映射
    CREDIBILITY_MAP = {
        # 高可信度：官方来源
        "sec": "high",
        # 中可信度：专业金融媒体
        "finnhub": "medium",
        "polygon": "medium",
        # 默认
        "default": "low"
    }
    
    def __init__(self):
        self.deduplicator = Deduplicator()
    
    def normalize(self, raw_items: List[RawNewsData]) -> List[Tuple[RawItemCreate, NewsItemCreate]]:
        """
        标准化原始数据
        
        Args:
            raw_items: 原始数据列表
        
        Returns:
            (RawItemCreate, NewsItemCreate) 元组列表
            RawItemCreate 用于保存原始数据
            NewsItemCreate 用于保存标准化数据
        """
        results = []
        
        for raw in raw_items:
            try:
                raw_create, news_create = self._normalize_item(raw)
                results.append((raw_create, news_create))
            except Exception as e:
                logger.warning(
                    "Failed to normalize item",
                    url=raw.url,
                    error=str(e)
                )
        
        logger.info(
            "Normalization completed",
            input_count=len(raw_items),
            output_count=len(results)
        )
        
        return results
    
    def _normalize_item(self, raw: RawNewsData) -> Tuple[RawItemCreate, NewsItemCreate]:
        """标准化单个条目"""
        
        # 创建原始数据记录
        raw_create = RawItemCreate(
            source=raw.source,
            source_type=raw.source_type,
            external_id=raw.external_id,
            url=raw.url,
            raw_payload=raw.raw_payload
        )
        
        # 规范化 URL
        canonical_url = self.deduplicator.canonicalize_url(raw.url)
        
        # 规范化标题
        title_normalized = self.deduplicator.normalize_title(raw.title)
        
        # 计算内容哈希
        content_hash = self.deduplicator.compute_content_hash(raw)
        
        # 确定可信度
        credibility = self._determine_credibility(raw.source, raw.source_type)
        
        # 确保发布时间
        published_at = raw.published_at or datetime.utcnow()
        
        # 创建标准化新闻记录
        news_create = NewsItemCreate(
            canonical_url=canonical_url,
            title=raw.title,
            title_normalized=title_normalized,
            content_hash=content_hash,
            summary=raw.summary,
            published_at=published_at,
            source=raw.source,
            source_type=raw.source_type,
            credibility=credibility,
            tickers=raw.tickers,
        )
        
        return raw_create, news_create
    
    def _determine_credibility(self, source: str, source_type: str) -> str:
        """
        根据来源确定可信度
        
        - SEC 公告 = high
        - 专业财经媒体 = medium
        - 其他 = low
        """
        # Filing 类型自动提升为 high
        if source_type == "filing":
            return "high"
        
        return self.CREDIBILITY_MAP.get(source, self.CREDIBILITY_MAP["default"])


class DataProcessor:
    """
    数据处理器 - 整合标准化和去重
    
    流程: Raw Data → Normalize → Deduplicate → Ready for AI
    """
    
    def __init__(self, similarity_threshold: float = 0.85):
        self.normalizer = Normalizer()
        self.deduplicator = Deduplicator(similarity_threshold)
    
    def process(
        self,
        raw_items: List[RawNewsData]
    ) -> Tuple[List[Tuple[RawItemCreate, NewsItemCreate]], int, int]:
        """
        处理原始数据
        
        Args:
            raw_items: 原始数据列表
        
        Returns:
            (normalized_items, total_before_dedup, removed_count)
        """
        if not raw_items:
            return [], 0, 0
        
        # Step 1: 先去重原始数据
        dedup_result = self.deduplicator.deduplicate(raw_items)
        
        # Step 2: 标准化去重后的数据
        normalized = self.normalizer.normalize(dedup_result.kept_items)
        
        logger.info(
            "Data processing completed",
            raw_count=len(raw_items),
            after_dedup=len(dedup_result.kept_items),
            removed=dedup_result.removed_count,
            normalized=len(normalized)
        )
        
        return normalized, len(raw_items), dedup_result.removed_count
