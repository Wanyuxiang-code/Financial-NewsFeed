"""Pipeline 流水线 - 整合采集、处理、分析、输出"""
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from uuid import UUID
import asyncio
import yaml
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import async_session_maker, WatchlistItem
from app.models.schemas import (
    NewsItemCreate, RawItemCreate, AnalysisResultCreate,
    PipelineRunUpdate, DeliveryLogCreate, DeliveryLogUpdate
)
from app.models import crud
from app.collectors.base import RawNewsData
from app.collectors.finnhub import FinnhubNewsCollector
from app.collectors.sec_edgar import SECFilingCollector
from app.core.normalizer import DataProcessor
from app.providers.factory import get_ai_provider
from app.providers.base import AIAnalysisError
from app.outputs.base import Digest, DigestItem, TickerSummary
from app.outputs.notion import NotionOutput
from app.outputs.markdown import MarkdownOutput
from app.utils.logger import get_logger, set_run_id, get_run_id

logger = get_logger(__name__)


class Pipeline:
    """
    新闻处理流水线
    
    流程:
    1. 加载 Watchlist
    2. 采集新闻 (Finnhub, SEC)
    3. 标准化 + 去重
    4. AI 分析
    5. 保存到数据库
    6. 输出到 Notion
    """
    
    def __init__(
        self,
        hours_lookback: int = 24,
        tickers: Optional[List[str]] = None,
        limit_per_ticker: Optional[int] = None
    ):
        self.hours_lookback = hours_lookback
        self.specified_tickers = tickers
        self.limit_per_ticker = limit_per_ticker
        
        # 统计
        self.stats = {
            "raw_collected": 0,
            "after_normalize": 0,
            "after_dedup": 0,
            "analyzed_success": 0,
            "analyzed_failed": 0,
            "delivered": 0,
        }
    
    async def run(self, run_id: Optional[UUID] = None) -> Digest:
        """
        运行完整流水线
        
        Args:
            run_id: 运行 ID（用于追踪）
        
        Returns:
            生成的摘要
        """
        # 设置 run_id
        if run_id:
            set_run_id(run_id)
        else:
            run_id = get_run_id() or set_run_id()
        
        logger.info("Pipeline started", run_id=str(run_id))
        
        try:
            # Step 1: 加载 Watchlist
            watchlist = await self._load_watchlist()
            tickers = self.specified_tickers or [item["ticker"] for item in watchlist]
            thesis_map = {item["ticker"]: item.get("thesis", "") for item in watchlist}
            
            logger.info(f"Watchlist loaded: {len(tickers)} tickers")
            
            # Step 2: 计算时间窗口
            window_end = datetime.utcnow()
            window_start = window_end - timedelta(hours=self.hours_lookback)
            
            # Step 3: 采集新闻
            raw_items = await self._collect_news(tickers, window_start, window_end)
            self.stats["raw_collected"] = len(raw_items)
            
            logger.info(f"Collected {len(raw_items)} raw items")
            
            # Step 4: 标准化 + 去重
            processor = DataProcessor()
            normalized_items, total_before, removed = processor.process(raw_items)
            self.stats["after_normalize"] = len(normalized_items)
            self.stats["after_dedup"] = len(normalized_items)
            
            logger.info(f"After processing: {len(normalized_items)} items (removed {removed})")
            
            # Step 4.5: 如果设置了限制，每只股票只保留 N 条新闻
            if self.limit_per_ticker:
                limited_items = []
                ticker_counts: Dict[str, int] = {}
                
                for item in normalized_items:
                    raw_create, news_create = item
                    # 检查该新闻的所有股票是否已达上限
                    should_include = False
                    if news_create.tickers:
                        for ticker in news_create.tickers:
                            count = ticker_counts.get(ticker, 0)
                            if count < self.limit_per_ticker:
                                should_include = True
                                break
                    else:
                        should_include = True
                    
                    if should_include:
                        limited_items.append(item)
                        if news_create.tickers:
                            for ticker in news_create.tickers:
                                ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1
                
                original_count = len(normalized_items)
                normalized_items = limited_items
                logger.info(f"Limited to {len(normalized_items)} items (limit: {self.limit_per_ticker}/ticker, was: {original_count})")
            
            # Step 5: 保存到数据库并进行 AI 分析
            digest_items = await self._analyze_and_save(normalized_items, thesis_map)
            
            # Step 6: 生成每只股票的汇总分析
            ticker_summaries = await self._generate_ticker_summaries(
                digest_items, watchlist, thesis_map
            )
            
            # Step 7: 创建 Digest
            digest = Digest(
                run_id=str(run_id),
                generated_at=datetime.utcnow(),
                window_start=window_start,
                window_end=window_end,
                items=digest_items,
                total_collected=self.stats["raw_collected"],
                total_after_dedup=self.stats["after_dedup"],
                total_analyzed=self.stats["analyzed_success"],
                total_failed=self.stats["analyzed_failed"],
                ticker_summaries=ticker_summaries,
            )
            
            # Step 7: 输出
            if "notion" in settings.outputs:
                await self._deliver_to_notion(digest, run_id)
            
            if "markdown" in settings.outputs:
                await self._deliver_to_markdown(digest, run_id)
            
            # 更新 Pipeline Run 状态
            await self._update_pipeline_run(run_id, "success")
            
            logger.info(
                "Pipeline completed",
                run_id=str(run_id),
                stats=self.stats
            )
            
            return digest
            
        except Exception as e:
            logger.error(f"Pipeline failed: {e}", run_id=str(run_id))
            await self._update_pipeline_run(run_id, "failed", str(e))
            raise
    
    async def _load_watchlist(self) -> List[Dict]:
        """从 YAML 文件或数据库加载 Watchlist"""
        # 优先从 YAML 加载
        yaml_path = Path(settings.watchlist_path)
        if yaml_path.exists():
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                return data.get("watchlist", [])
        
        # 从数据库加载
        async with async_session_maker() as db:
            items = await crud.get_watchlist(db)
            return [
                {
                    "ticker": item.ticker,
                    "company_name": item.company_name,
                    "thesis": item.thesis,
                    "risk_tags": item.risk_tags,
                    "priority": item.priority,
                    "sector": item.sector,
                }
                for item in items
            ]
    
    async def _collect_news(
        self,
        tickers: List[str],
        since: datetime,
        until: datetime
    ) -> List[RawNewsData]:
        """从所有数据源采集新闻"""
        all_items: List[RawNewsData] = []
        
        # Finnhub (中可信度新闻)
        if settings.finnhub_enabled:
            try:
                async with FinnhubNewsCollector() as collector:
                    items = await collector.collect(tickers, since, until)
                    all_items.extend(items)
                    logger.info(f"Finnhub collected {len(items)} items")
            except Exception as e:
                logger.error(f"Finnhub collection failed: {e}")
        
        # SEC EDGAR (高可信度公告)
        if settings.sec_enabled:
            try:
                async with SECFilingCollector() as collector:
                    items = await collector.collect(tickers, since, until)
                    all_items.extend(items)
                    logger.info(f"SEC collected {len(items)} filings")
            except Exception as e:
                logger.error(f"SEC collection failed: {e}")
        
        return all_items
    
    async def _analyze_and_save(
        self,
        normalized_items: List[tuple],
        thesis_map: Dict[str, str]
    ) -> List[DigestItem]:
        """AI 分析并保存到数据库"""
        digest_items: List[DigestItem] = []
        
        # 获取 AI Provider
        try:
            provider = get_ai_provider()
        except Exception as e:
            logger.error(f"Failed to create AI provider: {e}")
            # 没有 AI，仍然保存新闻但不分析
            async with async_session_maker() as db:
                for raw_create, news_create in normalized_items:
                    # 保存原始数据
                    raw_item = await crud.create_raw_item(db, raw_create)
                    news_create.raw_item_id = raw_item.id
                    
                    # 保存新闻
                    await crud.create_news_item(db, news_create)
                    
                    digest_items.append(DigestItem(news=news_create, analysis=None))
                
                await db.commit()
            
            return digest_items
        
        # 有 AI，进行分析
        logger.info(f"Starting AI analysis for {len(normalized_items)} items")
        try:
            async with provider:
                async with async_session_maker() as db:
                    for i, (raw_create, news_create) in enumerate(normalized_items):
                        logger.info(f"Processing item {i+1}/{len(normalized_items)}: {news_create.title[:40]}")
                        
                        # 检查是否已存在（URL 或 Hash 去重）
                        existing = await crud.get_news_item_by_url(db, news_create.canonical_url)
                        if existing:
                            logger.info(f"Skipping duplicate item {i+1}")
                            continue
                        
                        logger.info(f"Analyzing item {i+1}...")
                        
                        # 保存原始数据
                        raw_item = await crud.create_raw_item(db, raw_create)
                        news_create.raw_item_id = raw_item.id
                        
                        # 保存新闻
                        news_item = await crud.create_news_item(db, news_create)
                        
                        # AI 分析
                        analysis = None
                        try:
                            # 获取相关 thesis
                            thesis = ""
                            if news_create.tickers:
                                for ticker in news_create.tickers:
                                    if ticker in thesis_map:
                                        thesis = thesis_map[ticker]
                                        break
                            
                            analysis_output, tokens, cost = await provider.analyze(
                                news_create, thesis
                            )
                            
                            # 保存分析结果
                            analysis_create = AnalysisResultCreate(
                                news_item_id=news_item.id,
                                provider=provider.provider_name,
                                model=provider.model_name,
                                prompt_version=provider.prompt_version,
                                event_type=analysis_output.event_type,
                                impact_direction=analysis_output.impact_direction,
                                impact_horizon=analysis_output.impact_horizon,
                                thesis_relation=analysis_output.thesis_relation,
                                confidence=analysis_output.confidence,
                                confidence_reason=analysis_output.confidence_reason,
                                summary=analysis_output.summary,
                                key_facts=analysis_output.key_facts,
                                watch_next=analysis_output.watch_next,
                                tokens_used=tokens,
                                cost_usd=cost,
                            )
                            await crud.create_analysis_result(db, analysis_create)
                            
                            analysis = analysis_output
                            self.stats["analyzed_success"] += 1
                            
                        except Exception as e:
                            logger.warning(f"Analysis failed for {news_create.title[:50]}: {type(e).__name__}: {e}")
                            self.stats["analyzed_failed"] += 1
                        
                        digest_items.append(DigestItem(news=news_create, analysis=analysis))
                    
                    await db.commit()
        except Exception as e:
            logger.error(f"Error during AI analysis: {e}")
            raise
        
        return digest_items
    
    async def _deliver_to_notion(self, digest: Digest, run_id: UUID):
        """输出到 Notion"""
        try:
            async with async_session_maker() as db:
                # 创建 delivery log
                log = await crud.create_delivery_log(db, DeliveryLogCreate(
                    run_id=str(run_id),
                    channel="notion",
                    status="pending"
                ))
                await db.commit()
                
                # 发送
                async with NotionOutput() as output:
                    page_id = await output.deliver(digest)
                
                # 更新状态
                await crud.update_delivery_log(db, log.id, DeliveryLogUpdate(
                    status="success",
                    notion_page_id=page_id
                ))
                await db.commit()
                
                self.stats["delivered"] += 1
                logger.info(f"Delivered to Notion: {page_id}")
                
        except Exception as e:
            logger.error(f"Notion delivery failed: {e}")
            async with async_session_maker() as db:
                # 尝试更新失败状态
                try:
                    await crud.update_delivery_log(db, log.id, DeliveryLogUpdate(
                        status="failed",
                        error_message=str(e)
                    ))
                    await db.commit()
                except:
                    pass
    
    async def _deliver_to_markdown(self, digest: Digest, run_id: UUID):
        """输出到 Markdown 文件"""
        try:
            async with MarkdownOutput() as output:
                filepath = await output.deliver(digest)
            
            self.stats["delivered"] += 1
            logger.info(f"Delivered to Markdown: {filepath}")
            
        except Exception as e:
            logger.error(f"Markdown delivery failed: {e}")
    
    async def _generate_ticker_summaries(
        self,
        digest_items: List[DigestItem],
        watchlist: List[Dict],
        thesis_map: Dict[str, str]
    ) -> Dict[str, TickerSummary]:
        """为每只股票生成汇总分析"""
        summaries: Dict[str, TickerSummary] = {}
        
        # 按 ticker 分组
        by_ticker: Dict[str, List[DigestItem]] = {}
        for item in digest_items:
            if item.news.tickers:
                for ticker in item.news.tickers:
                    if ticker not in by_ticker:
                        by_ticker[ticker] = []
                    by_ticker[ticker].append(item)
        
        if not by_ticker:
            return summaries
        
        # 获取公司名称映射
        company_names = {item["ticker"]: item.get("company_name", item["ticker"]) for item in watchlist}
        
        # 使用 AI 生成汇总
        try:
            provider = get_ai_provider()
        except Exception as e:
            logger.warning(f"No AI provider for ticker summaries: {e}")
            # 无 AI 时返回基础统计
            for ticker, items in by_ticker.items():
                bullish = sum(1 for i in items if i.analysis and i.analysis.impact_direction == "bullish")
                bearish = sum(1 for i in items if i.analysis and i.analysis.impact_direction == "bearish")
                neutral = len(items) - bullish - bearish
                
                summaries[ticker] = TickerSummary(
                    ticker=ticker,
                    company_name=company_names.get(ticker, ticker),
                    news_count=len(items),
                    overall_sentiment="bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral",
                    summary=f"Today: {len(items)} news items ({bullish} bullish, {bearish} bearish)",
                    key_events=[i.news.title[:60] for i in items[:3]],
                    thesis_impact="Requires manual assessment",
                    action_suggestion="Continue monitoring",
                    risk_alerts=[],
                    bullish_count=bullish,
                    bearish_count=bearish,
                    neutral_count=neutral,
                )
            return summaries
        
        # 有 AI 时生成详细汇总
        logger.info(f"Generating AI summaries for {len(by_ticker)} tickers...")
        
        async with provider:
            for ticker, items in by_ticker.items():
                try:
                    company_name = company_names.get(ticker, ticker)
                    thesis = thesis_map.get(ticker, "")
                    
                    # 准备新闻数据
                    news_items = [(item.news, item.analysis) for item in items]
                    
                    # 调用 AI 生成汇总
                    summary_data, tokens, cost = await provider.generate_ticker_summary(
                        ticker=ticker,
                        company_name=company_name,
                        news_items=news_items,
                        thesis=thesis
                    )
                    
                    # 统计情绪
                    bullish = sum(1 for i in items if i.analysis and i.analysis.impact_direction == "bullish")
                    bearish = sum(1 for i in items if i.analysis and i.analysis.impact_direction == "bearish")
                    neutral = len(items) - bullish - bearish
                    
                    summaries[ticker] = TickerSummary(
                        ticker=ticker,
                        company_name=company_name,
                        news_count=len(items),
                        overall_sentiment=summary_data.get("overall_sentiment", "neutral"),
                        summary=summary_data.get("summary", ""),
                        key_events=summary_data.get("key_events", [])[:3],
                        thesis_impact=summary_data.get("thesis_impact", ""),
                        action_suggestion=summary_data.get("action_suggestion", "继续观察"),
                        risk_alerts=summary_data.get("risk_alerts", []),
                        bullish_count=bullish,
                        bearish_count=bearish,
                        neutral_count=neutral,
                    )
                    
                    logger.info(f"Generated summary for {ticker}: {summary_data.get('overall_sentiment')}")
                    
                except Exception as e:
                    logger.warning(f"Failed to generate summary for {ticker}: {e}")
                    # 添加基础汇总
                    bullish = sum(1 for i in items if i.analysis and i.analysis.impact_direction == "bullish")
                    bearish = sum(1 for i in items if i.analysis and i.analysis.impact_direction == "bearish")
                    
                    summaries[ticker] = TickerSummary(
                        ticker=ticker,
                        company_name=company_names.get(ticker, ticker),
                        news_count=len(items),
                        overall_sentiment="bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral",
                        summary=f"Today: {len(items)} news items ({bullish} bullish, {bearish} bearish)",
                        key_events=[i.news.title[:60] for i in items[:3]],
                        thesis_impact="Summary generation failed",
                        action_suggestion="Continue monitoring",
                        risk_alerts=[],
                        bullish_count=bullish,
                        bearish_count=bearish,
                        neutral_count=len(items) - bullish - bearish,
                    )
        
        return summaries
    
    async def _update_pipeline_run(
        self,
        run_id: UUID,
        status: str,
        error_log: Optional[str] = None
    ):
        """更新 Pipeline Run 状态"""
        try:
            async with async_session_maker() as db:
                await crud.update_pipeline_run(db, run_id, PipelineRunUpdate(
                    finished_at=datetime.utcnow(),
                    status=status,
                    raw_collected=self.stats["raw_collected"],
                    after_normalize=self.stats["after_normalize"],
                    after_dedup=self.stats["after_dedup"],
                    analyzed_success=self.stats["analyzed_success"],
                    analyzed_failed=self.stats["analyzed_failed"],
                    delivered=self.stats["delivered"],
                    error_log=error_log,
                ))
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to update pipeline run: {e}")


async def run_pipeline(
    run_id: Optional[UUID] = None,
    hours_lookback: int = 24,
    tickers: Optional[List[str]] = None,
    limit_per_ticker: Optional[int] = None
) -> Digest:
    """
    运行 Pipeline 的便捷函数（用于 API 和 CLI）
    """
    pipeline = Pipeline(hours_lookback=hours_lookback, tickers=tickers, limit_per_ticker=limit_per_ticker)
    return await pipeline.run(run_id)
