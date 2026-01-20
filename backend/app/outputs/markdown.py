"""Markdown 文件输出 - 本地保存摘要（支持 K 线图和美化格式）"""
from typing import Optional, Dict, Set, List
from datetime import datetime
from pathlib import Path

from app.outputs.base import BaseOutput, Digest, DigestItem, OutputError
from app.utils.logger import get_logger
from app.config import settings

logger = get_logger(__name__)


class MarkdownOutput(BaseOutput):
    """
    Markdown 文件输出
    
    将摘要保存为本地 Markdown 文件，可选生成 K 线图
    """
    
    name = "markdown"
    
    def __init__(
        self,
        output_dir: Optional[str] = None,
        include_charts: bool = True,
        chart_days: int = 30
    ):
        self.output_dir = Path(output_dir or "data/digests")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.include_charts = include_charts
        self.chart_days = chart_days
        self._chart_generator = None
        logger.info(f"MarkdownOutput initialized, output_dir: {self.output_dir}")
    
    def _get_chart_generator(self):
        """延迟加载图表生成器"""
        if self._chart_generator is None:
            try:
                from app.utils.charts import ChartGenerator
                charts_dir = self.output_dir / "charts"
                self._chart_generator = ChartGenerator(str(charts_dir))
            except ImportError:
                logger.warning("Chart generation not available - missing dependencies")
                self._chart_generator = False
        return self._chart_generator if self._chart_generator else None
    
    async def deliver(self, digest: Digest) -> str:
        """生成并保存 Markdown 文件"""
        try:
            # 生成文件名
            date_str = digest.generated_at.strftime("%Y-%m-%d_%H%M")
            filename = f"digest_{date_str}.md"
            filepath = self.output_dir / filename
            
            # 收集所有涉及的 tickers
            tickers: Set[str] = set()
            for item in digest.items:
                if item.news.tickers:
                    tickers.update(item.news.tickers)
            
            # 生成图表
            chart_paths: Dict[str, str] = {}
            if self.include_charts and tickers:
                chart_gen = self._get_chart_generator()
                if chart_gen:
                    logger.info(f"Generating charts for {len(tickers)} tickers...")
                    for ticker in sorted(tickers):
                        try:
                            path = chart_gen.generate_price_chart(ticker, self.chart_days)
                            if path:
                                # 使用相对于 Markdown 文件所在目录的路径
                                chart_path = Path(path)
                                try:
                                    rel_path = chart_path.relative_to(self.output_dir)
                                except ValueError:
                                    # 如果无法计算相对路径，使用文件名
                                    rel_path = Path("charts") / chart_path.name
                                chart_paths[ticker] = str(rel_path).replace("\\", "/")
                        except Exception as e:
                            logger.warning(f"Failed to generate chart for {ticker}: {e}")
            
            # 生成 Markdown 内容
            content = self._build_markdown(digest, chart_paths)
            
            # 写入文件
            filepath.write_text(content, encoding="utf-8")
            
            logger.info(f"Digest saved to {filepath}", items=len(digest.items))
            
            return str(filepath)
            
        except Exception as e:
            logger.error(f"Failed to save digest: {e}")
            raise OutputError(f"Markdown output failed: {e}")
    
    def _build_markdown(self, digest: Digest, chart_paths: Dict[str, str] = None) -> str:
        """构建美化的 Markdown 内容"""
        chart_paths = chart_paths or {}
        lines = []
        
        date_str = digest.generated_at.strftime("%Y-%m-%d")
        time_str = digest.generated_at.strftime("%H:%M UTC")
        
        # ===== 头部 =====
        lines.append(f"# 📰 Daily Stock News Digest")
        lines.append(f"### {date_str} | Generated at {time_str}")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # ===== 情绪仪表盘 =====
        bullish = sum(1 for i in digest.items if i.analysis and i.analysis.impact_direction == "bullish")
        bearish = sum(1 for i in digest.items if i.analysis and i.analysis.impact_direction == "bearish")
        neutral = sum(1 for i in digest.items if i.analysis and i.analysis.impact_direction == "neutral")
        total = bullish + bearish + neutral
        
        # 计算情绪分数
        if total > 0:
            sentiment_score = ((bullish - bearish) / total) * 100
            if sentiment_score > 20:
                overall_mood = "🟢 BULLISH"
                mood_desc = "Market sentiment is positive"
            elif sentiment_score < -20:
                overall_mood = "🔴 BEARISH"
                mood_desc = "Market sentiment is negative"
            else:
                overall_mood = "🟡 MIXED"
                mood_desc = "Market sentiment is mixed"
        else:
            overall_mood = "⚪ NEUTRAL"
            mood_desc = "Insufficient data"
            sentiment_score = 0
        
        lines.append("## 📊 Market Sentiment Dashboard")
        lines.append("")
        lines.append(f"> **Overall: {overall_mood}**")
        lines.append(f"> ")
        lines.append(f"> {mood_desc}")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|:-------|------:|")
        lines.append(f"| 📈 Bullish News | **{bullish}** |")
        lines.append(f"| 📉 Bearish News | **{bearish}** |")
        lines.append(f"| ➖ Neutral News | **{neutral}** |")
        lines.append(f"| 📰 Total Analyzed | **{digest.total_analyzed}** |")
        lines.append(f"| ⏰ Time Window | {digest.window_start.strftime('%m/%d %H:%M')} - {digest.window_end.strftime('%m/%d %H:%M')} |")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # ===== 高影响力新闻 =====
        high_impact = digest.high_impact_items
        if high_impact:
            lines.append("## 🔥 Top Stories")
            lines.append("")
            lines.append("> The most significant news items that could impact your portfolio")
            lines.append("")
            
            for i, item in enumerate(high_impact[:5], 1):
                lines.extend(self._format_top_story(item, i))
            
            lines.append("---")
            lines.append("")
        
        # ===== 按股票分组 =====
        by_ticker = digest.by_ticker
        if by_ticker:
            lines.append("## 📈 Analysis by Ticker")
            lines.append("")
            
            # 按优先级排序（有汇总的优先）
            sorted_tickers = sorted(
                by_ticker.items(),
                key=lambda x: (
                    0 if x[0] in digest.ticker_summaries else 1,
                    x[0]
                )
            )
            
            for ticker, items in sorted_tickers:
                summary = digest.ticker_summaries.get(ticker)
                lines.extend(self._format_ticker_section(ticker, items, summary, chart_paths.get(ticker)))
        
        # ===== 页脚 =====
        lines.append("---")
        lines.append("")
        lines.append("<details>")
        lines.append("<summary>📋 View All News Items</summary>")
        lines.append("")
        lines.append("| Time | Ticker | Impact | Title |")
        lines.append("|:-----|:-------|:------:|:------|")
        
        for item in sorted(digest.items, key=lambda x: x.news.published_at, reverse=True):
            time_str = item.news.published_at.strftime("%H:%M")
            tickers = ", ".join(item.news.tickers) if item.news.tickers else "-"
            impact = "📈" if item.analysis and item.analysis.impact_direction == "bullish" else \
                     "📉" if item.analysis and item.analysis.impact_direction == "bearish" else "➖"
            title = item.news.title[:60] + "..." if len(item.news.title) > 60 else item.news.title
            lines.append(f"| {time_str} | {tickers} | {impact} | {title} |")
        
        lines.append("")
        lines.append("</details>")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"*🤖 Generated by NewsFeed AI | {digest.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}*")
        lines.append("")
        lines.append("*Data sources: Finnhub, SEC EDGAR | Analysis: Gemini AI*")
        
        return "\n".join(lines)
    
    def _format_top_story(self, item: DigestItem, index: int) -> List[str]:
        """格式化头条新闻"""
        lines = []
        news = item.news
        analysis = item.analysis
        
        # 影响指示器
        if analysis:
            impact_badge = "🟢 BULLISH" if analysis.impact_direction == "bullish" else \
                          "🔴 BEARISH" if analysis.impact_direction == "bearish" else "⚪ NEUTRAL"
        else:
            impact_badge = "❓ UNANALYZED"
        
        tickers = " ".join(f"`${t}`" for t in news.tickers) if news.tickers else ""
        
        lines.append(f"### {index}. {news.title}")
        lines.append("")
        lines.append(f"**{tickers}** | {impact_badge} | {news.published_at.strftime('%m/%d %H:%M')}")
        lines.append("")
        
        if analysis:
            lines.append(f"> 📝 **Summary**: {analysis.summary}")
            lines.append(">")
            
            if analysis.key_facts:
                lines.append("> **Key Facts**:")
                for fact in analysis.key_facts[:3]:
                    lines.append(f"> - {fact}")
                lines.append(">")
            
            lines.append(f"> 🎯 **Thesis Impact**: {analysis.thesis_relation.upper()} | ⏱️ **Horizon**: {analysis.impact_horizon}")
            
            if analysis.watch_next:
                lines.append(f">")
                lines.append(f"> 👀 **Watch**: {analysis.watch_next}")
        
        lines.append("")
        lines.append(f"🔗 [Read more]({news.canonical_url}) | Source: {news.source}")
        lines.append("")
        
        return lines
    
    def _format_ticker_section(
        self,
        ticker: str,
        items: List[DigestItem],
        summary,
        chart_path: Optional[str]
    ) -> List[str]:
        """格式化单个股票的部分"""
        lines = []
        
        # 标题
        if summary:
            sentiment_badge = {
                "bullish": "🟢",
                "bearish": "🔴",
                "neutral": "⚪",
                "mixed": "🟡"
            }.get(summary.overall_sentiment, "❓")
            company = summary.company_name
        else:
            sentiment_badge = "📊"
            company = ticker
        
        lines.append(f"### {sentiment_badge} ${ticker} - {company}")
        lines.append("")
        
        # K线图
        if chart_path:
            lines.append(f"![{ticker} 30-Day Price Chart]({chart_path})")
            lines.append("")
        
        # AI 汇总卡片
        if summary:
            lines.append(f"**🤖 AI Daily Analysis**")
            lines.append("")
            lines.append(f"| | |")
            lines.append(f"|:--|:--|")
            
            sentiment_text = {
                "bullish": "📈 Bullish",
                "bearish": "📉 Bearish", 
                "neutral": "➖ Neutral",
                "mixed": "🔄 Mixed"
            }.get(summary.overall_sentiment, "Unknown")
            
            lines.append(f"| **Sentiment** | {sentiment_text} ({summary.bullish_count}↑ {summary.bearish_count}↓ {summary.neutral_count}→) |")
            lines.append(f"| **Summary** | {summary.summary} |")
            
            if summary.thesis_impact:
                lines.append(f"| **Thesis Impact** | {summary.thesis_impact} |")
            
            if summary.action_suggestion:
                action_icon = {
                    "Continue monitoring": "👀",
                    "Wait for earnings/data": "📅",
                    "Add on pullback": "💰",
                    "Reduce and watch": "⚠️",
                    "Hold position": "🔒"
                }.get(summary.action_suggestion, "💡")
                lines.append(f"| **Suggestion** | {action_icon} {summary.action_suggestion} |")
            
            lines.append("")
            
            if summary.key_events:
                lines.append("**Key Events:**")
                for event in summary.key_events[:3]:
                    lines.append(f"- {event}")
                lines.append("")
            
            if summary.risk_alerts:
                lines.append("**⚠️ Risk Alerts:**")
                for risk in summary.risk_alerts[:2]:
                    lines.append(f"- {risk}")
                lines.append("")
        
        # 新闻列表
        lines.append(f"**Today's News ({len(items)} items):**")
        lines.append("")
        
        for item in items[:5]:
            news = item.news
            analysis = item.analysis
            
            impact = "📈" if analysis and analysis.impact_direction == "bullish" else \
                     "📉" if analysis and analysis.impact_direction == "bearish" else "➖"
            
            time_str = news.published_at.strftime("%H:%M")
            lines.append(f"- {impact} **[{time_str}]** {news.title}")
            
            if analysis and analysis.summary:
                lines.append(f"  - _{analysis.summary}_")
        
        if len(items) > 5:
            lines.append(f"  - _... and {len(items) - 5} more_")
        
        lines.append("")
        
        return lines
    
    async def close(self):
        """关闭（无操作）"""
        pass
