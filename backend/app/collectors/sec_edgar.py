"""SEC EDGAR Filing Collector - 高可信度公告源"""
from datetime import datetime, timedelta
from typing import List, Optional, Dict
import asyncio

import httpx

from app.collectors.base import BaseCollector, RawNewsData
from app.utils.rate_limiter import RateLimitedClient, rate_limiter
from app.utils.logger import get_logger
from app.config import settings

logger = get_logger(__name__)


# CIK (Central Index Key) 映射表 - 常见股票
# 可以通过 SEC 的 company_tickers.json 获取完整列表
CIK_MAP = {
    "AAPL": "320193",
    "GOOGL": "1652044",
    "GOOG": "1652044",
    "MSFT": "789019",
    "AMZN": "1018724",
    "NVDA": "1045810",
    "TSM": "1046179",
    "AMD": "2488",
    "INTC": "50863",
    "MU": "723125",
    "WDC": "106040",
    "RKLB": "1819994",
    "META": "1326801",
    "TSLA": "1318605",
    "AVGO": "1730168",
    "MRVL": "1058057",
}


class SECClient(RateLimitedClient):
    """
    SEC EDGAR API 客户端
    
    重要约束:
    - 最大 10 requests/second
    - 必须设置 User-Agent (包含联系邮箱)
    """
    
    api_name = "sec"
    base_url = "https://data.sec.gov"
    timeout = 30.0
    
    def __init__(self, user_agent: Optional[str] = None):
        super().__init__()
        self.user_agent = user_agent or settings.sec_user_agent
    
    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "application/json",
                }
            )
        return self._client
    
    async def get_company_filings(
        self,
        cik: str,
        form_types: Optional[List[str]] = None
    ) -> Dict:
        """
        获取公司的 filings 列表
        
        API: GET /submissions/CIK{cik}.json
        
        Args:
            cik: Central Index Key (需要补零到10位)
            form_types: 过滤的表单类型，如 ["8-K", "10-Q", "10-K", "4"]
        
        Returns:
            公司 filings 数据，包含:
            - cik, name, sic, sicDescription
            - filings.recent: 最近的 filings 列表
        """
        # CIK 补零到 10 位
        cik_padded = cik.zfill(10)
        
        response = await self.get(f"/submissions/CIK{cik_padded}.json")
        data = response.json()
        
        return data
    
    async def get_company_ticker_map(self) -> Dict[str, str]:
        """
        获取 ticker -> CIK 映射
        
        API: GET /files/company_tickers.json
        """
        response = await self.get("/files/company_tickers.json")
        data = response.json()
        
        # 转换格式: {ticker: cik}
        result = {}
        for item in data.values():
            ticker = item.get("ticker", "")
            cik = str(item.get("cik_str", ""))
            if ticker and cik:
                result[ticker.upper()] = cik
        
        return result


class SECFilingCollector(BaseCollector):
    """
    SEC EDGAR Filing 采集器
    
    - 数据源: SEC EDGAR API
    - 类型: Filing (公告)
    - 可信度: 高（官方监管文件）
    
    支持的 Filing 类型:
    - 8-K: 重大事件报告
    - 10-Q: 季度报告
    - 10-K: 年度报告
    - 4: 内部人交易报告 (Form 4)
    """
    
    source = "sec"
    source_type = "filing"
    credibility = "high"
    
    # 关注的 Filing 类型
    FILING_TYPES = ["8-K", "10-Q", "10-K", "4"]
    
    # 每种类型的描述
    FILING_DESCRIPTIONS = {
        "8-K": "Current Report (Material Event)",
        "10-Q": "Quarterly Report",
        "10-K": "Annual Report",
        "4": "Insider Trading Report",
        "SC 13G": "Beneficial Ownership Report",
        "SC 13D": "Beneficial Ownership Report (Active)",
    }
    
    def __init__(self, user_agent: Optional[str] = None):
        self.client = SECClient(user_agent)
        self._cik_cache: Dict[str, str] = CIK_MAP.copy()
    
    async def collect(
        self,
        tickers: List[str],
        since: datetime,
        until: Optional[datetime] = None
    ) -> List[RawNewsData]:
        """
        采集多个股票的 SEC Filings
        """
        if not settings.sec_enabled:
            logger.info("SEC collector is disabled")
            return []
        
        until = until or datetime.utcnow()
        
        all_filings: List[RawNewsData] = []
        
        # 并发采集（但受限流器控制）
        tasks = [
            self._collect_ticker(ticker, since, until)
            for ticker in tickers
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for ticker, result in zip(tickers, results):
            if isinstance(result, Exception):
                logger.error(
                    "Failed to collect SEC filings",
                    ticker=ticker,
                    error=str(result)
                )
                continue
            
            all_filings.extend(result)
        
        logger.info(
            "SEC collection completed",
            tickers=len(tickers),
            total_filings=len(all_filings)
        )
        
        return all_filings
    
    async def _collect_ticker(
        self,
        ticker: str,
        since: datetime,
        until: datetime
    ) -> List[RawNewsData]:
        """采集单个股票的 Filings"""
        ticker = ticker.upper()
        
        # 获取 CIK
        cik = await self._get_cik(ticker)
        if not cik:
            logger.warning(f"CIK not found for ticker: {ticker}")
            return []
        
        try:
            # 获取 filings
            data = await self.client.get_company_filings(cik)
            
            company_name = data.get("name", ticker)
            filings_data = data.get("filings", {}).get("recent", {})
            
            items = []
            
            # 解析 filings 列表
            forms = filings_data.get("form", [])
            accession_numbers = filings_data.get("accessionNumber", [])
            filing_dates = filings_data.get("filingDate", [])
            primary_documents = filings_data.get("primaryDocument", [])
            descriptions = filings_data.get("primaryDocDescription", [])
            
            for i in range(len(forms)):
                form_type = forms[i] if i < len(forms) else ""
                
                # 只处理关注的类型
                if form_type not in self.FILING_TYPES:
                    continue
                
                # 解析日期
                filing_date_str = filing_dates[i] if i < len(filing_dates) else ""
                try:
                    filing_date = datetime.strptime(filing_date_str, "%Y-%m-%d")
                except:
                    filing_date = datetime.utcnow()
                
                # 时间过滤
                if filing_date < since or filing_date > until:
                    continue
                
                # 构建 URL
                accession = accession_numbers[i] if i < len(accession_numbers) else ""
                accession_formatted = accession.replace("-", "")
                primary_doc = primary_documents[i] if i < len(primary_documents) else ""
                
                url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_formatted}/{primary_doc}"
                
                # 构建标题
                description = descriptions[i] if i < len(descriptions) else ""
                filing_desc = self.FILING_DESCRIPTIONS.get(form_type, form_type)
                title = f"[{form_type}] {company_name}: {description or filing_desc}"
                
                item = RawNewsData(
                    source=self.source,
                    source_type=self.source_type,
                    external_id=accession,
                    url=url,
                    title=title,
                    summary=f"{filing_desc} filed on {filing_date_str}",
                    published_at=filing_date,
                    tickers=[ticker],
                    raw_payload={
                        "form": form_type,
                        "accessionNumber": accession,
                        "filingDate": filing_date_str,
                        "companyName": company_name,
                        "cik": cik,
                    },
                    category=form_type,
                )
                
                items.append(item)
            
            logger.debug(
                "Collected SEC filings",
                ticker=ticker,
                count=len(items)
            )
            
            return items
            
        except Exception as e:
            logger.error(
                "Error collecting SEC filings",
                ticker=ticker,
                cik=cik,
                error=str(e)
            )
            raise
    
    async def _get_cik(self, ticker: str) -> Optional[str]:
        """获取 ticker 对应的 CIK"""
        ticker = ticker.upper()
        
        # 先查缓存
        if ticker in self._cik_cache:
            return self._cik_cache[ticker]
        
        # 从 SEC API 获取映射
        try:
            ticker_map = await self.client.get_company_ticker_map()
            self._cik_cache.update(ticker_map)
            return self._cik_cache.get(ticker)
        except Exception as e:
            logger.warning(f"Failed to fetch CIK map: {e}")
            return None
    
    async def close(self):
        """关闭客户端"""
        await self.client.close()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
