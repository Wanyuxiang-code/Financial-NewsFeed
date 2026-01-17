"""Finnhub 新闻采集器 - 中可信度新闻源"""
from datetime import datetime, timedelta
from typing import List, Optional
import asyncio

import httpx

from app.collectors.base import BaseCollector, RawNewsData
from app.utils.rate_limiter import RateLimitedClient, rate_limiter
from app.utils.logger import get_logger
from app.config import settings

logger = get_logger(__name__)


class FinnhubClient(RateLimitedClient):
    """Finnhub API 客户端"""
    
    api_name = "finnhub"
    base_url = "https://finnhub.io/api/v1"
    timeout = 30.0
    
    def __init__(self, api_key: Optional[str] = None):
        super().__init__()
        self.api_key = api_key or settings.finnhub_api_key
    
    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                params={"token": self.api_key},
            )
        return self._client
    
    async def get_company_news(
        self,
        ticker: str,
        from_date: str,
        to_date: str
    ) -> List[dict]:
        """
        获取公司新闻
        
        API: GET /company-news?symbol=AAPL&from=2023-01-01&to=2023-01-15
        
        Returns:
            新闻列表，每条包含:
            - id: 新闻ID
            - headline: 标题
            - summary: 摘要
            - source: 来源
            - url: 链接
            - datetime: Unix 时间戳
            - related: 相关股票代码
            - category: 分类
            - image: 图片URL
        """
        response = await self.get(
            "/company-news",
            params={
                "symbol": ticker.upper(),
                "from": from_date,
                "to": to_date,
            }
        )
        return response.json()
    
    async def get_market_news(self, category: str = "general") -> List[dict]:
        """
        获取市场新闻
        
        Args:
            category: general | forex | crypto | merger
        """
        response = await self.get(
            "/news",
            params={"category": category}
        )
        return response.json()


class FinnhubNewsCollector(BaseCollector):
    """
    Finnhub 新闻采集器
    
    - 数据源: Finnhub API
    - 类型: 新闻
    - 可信度: 中（聚合多来源的财经媒体新闻）
    """
    
    source = "finnhub"
    source_type = "news"
    credibility = "medium"
    
    def __init__(self, api_key: Optional[str] = None):
        self.client = FinnhubClient(api_key)
    
    async def collect(
        self,
        tickers: List[str],
        since: datetime,
        until: Optional[datetime] = None
    ) -> List[RawNewsData]:
        """
        采集多个股票的新闻
        
        为避免重复，会对所有结果按 URL 去重
        """
        if not settings.finnhub_enabled:
            logger.info("Finnhub collector is disabled")
            return []
        
        if not self.client.api_key:
            logger.error("Finnhub API key not configured")
            return []
        
        until = until or datetime.utcnow()
        
        # 格式化日期 (Finnhub 需要 YYYY-MM-DD 格式)
        from_date = since.strftime("%Y-%m-%d")
        to_date = until.strftime("%Y-%m-%d")
        
        all_news: List[RawNewsData] = []
        seen_urls: set = set()
        
        # 并发采集每个 ticker（但受限流器控制）
        tasks = [
            self._collect_ticker(ticker, from_date, to_date)
            for ticker in tickers
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for ticker, result in zip(tickers, results):
            if isinstance(result, Exception):
                logger.error(
                    "Failed to collect news",
                    ticker=ticker,
                    error=str(result)
                )
                continue
            
            # 去重
            for item in result:
                if item.url not in seen_urls:
                    seen_urls.add(item.url)
                    all_news.append(item)
        
        logger.info(
            "Finnhub collection completed",
            tickers=len(tickers),
            total_news=len(all_news),
            deduplicated_from=sum(len(r) for r in results if not isinstance(r, Exception))
        )
        
        return all_news
    
    async def _collect_ticker(
        self,
        ticker: str,
        from_date: str,
        to_date: str
    ) -> List[RawNewsData]:
        """采集单个股票的新闻"""
        try:
            raw_news = await self.client.get_company_news(ticker, from_date, to_date)
            
            items = []
            for news in raw_news:
                item = self._parse_news_item(news, ticker)
                if item:
                    items.append(item)
            
            logger.debug(
                "Collected ticker news",
                ticker=ticker,
                count=len(items)
            )
            
            return items
            
        except Exception as e:
            logger.error(
                "Error collecting ticker news",
                ticker=ticker,
                error=str(e)
            )
            raise
    
    def _parse_news_item(self, raw: dict, primary_ticker: str) -> Optional[RawNewsData]:
        """解析 Finnhub 新闻响应"""
        try:
            # 解析时间戳
            timestamp = raw.get("datetime")
            if timestamp:
                published_at = datetime.utcfromtimestamp(timestamp)
            else:
                published_at = datetime.utcnow()
            
            # 解析相关股票
            related = raw.get("related", "")
            if related:
                tickers = [t.strip() for t in related.split(",") if t.strip()]
            else:
                tickers = [primary_ticker.upper()]
            
            # 确保主要 ticker 在列表中
            if primary_ticker.upper() not in tickers:
                tickers.insert(0, primary_ticker.upper())
            
            return RawNewsData(
                source=self.source,
                source_type=self.source_type,
                external_id=str(raw.get("id", "")),
                url=raw.get("url", ""),
                title=raw.get("headline", ""),
                summary=raw.get("summary", ""),
                published_at=published_at,
                tickers=tickers,
                raw_payload=raw,
                author=raw.get("source", ""),
                category=raw.get("category", ""),
                image_url=raw.get("image", ""),
            )
            
        except Exception as e:
            logger.warning(
                "Failed to parse news item",
                error=str(e),
                raw=raw
            )
            return None
    
    async def close(self):
        """关闭客户端"""
        await self.client.close()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
