"""Notion 输出处理器 - 批量写入 + 节流"""
from typing import List, Optional, Any, Dict
from datetime import datetime
import asyncio

from app.outputs.base import BaseOutput, Digest, DigestItem, OutputError
from app.utils.rate_limiter import rate_limiter, RateLimitedClient
from app.utils.logger import get_logger
from app.config import settings

logger = get_logger(__name__)

# 延迟导入 Notion SDK
try:
    from notion_client import AsyncClient as NotionAsyncClient
    NOTION_AVAILABLE = True
except ImportError:
    NOTION_AVAILABLE = False
    logger.warning("notion-client not installed, Notion output unavailable")


class NotionOutput(BaseOutput):
    """
    Notion 输出处理器
    
    特性:
    - 批量写入优化（减少 API 调用）
    - 限流 (3 req/s)
    - 429 自动重试
    - 格式化为 Notion blocks
    
    输出格式:
    - 创建一个新的 Page 在指定的 Database 中
    - Page 属性包含日期、统计信息
    - Page 内容包含新闻摘要和分析
    """
    
    name = "notion"
    
    def __init__(
        self,
        token: Optional[str] = None,
        database_id: Optional[str] = None
    ):
        if not NOTION_AVAILABLE:
            raise OutputError("notion-client package not installed")
        
        self.token = token or settings.notion_token
        self.database_id = database_id or settings.notion_database_id
        
        if not self.token:
            raise OutputError("Notion token not configured")
        if not self.database_id:
            raise OutputError("Notion database ID not configured")
        
        self._client = NotionAsyncClient(auth=self.token)
        self._title_property = None  # Will be detected on first use
        
        logger.info("NotionOutput initialized")
    
    async def deliver(self, digest: Digest) -> str:
        """
        发送摘要到 Notion
        
        创建一个新的 Page，包含所有新闻和分析
        """
        try:
            # 检测数据库的 Title 属性名称
            if not self._title_property:
                await self._detect_title_property()
            
            # 构建 Page 属性
            properties = self._build_properties(digest)
            
            # 构建 Page 内容 (blocks)
            children = self._build_content_blocks(digest)
            
            # 创建 Page（使用限流）
            page = await self._create_page(properties, children)
            
            page_id = page["id"]
            logger.info(
                "Digest delivered to Notion",
                page_id=page_id,
                items=len(digest.items)
            )
            
            return page_id
            
        except Exception as e:
            logger.error(f"Failed to deliver digest to Notion: {e}")
            raise OutputError(f"Notion delivery failed: {e}")
    
    async def _detect_title_property(self):
        """检测数据库的 Title 属性名称"""
        try:
            db = await self._client.databases.retrieve(database_id=self.database_id)
            properties = db.get("properties", {})
            
            # 找到 Title 类型的属性
            for name, prop in properties.items():
                if prop.get("type") == "title":
                    self._title_property = name
                    logger.info(f"Detected title property: {name}")
                    return
            
            # 如果没找到，默认使用 "Name"
            self._title_property = "Name"
            logger.warning("No title property found, using default 'Name'")
            
        except Exception as e:
            logger.warning(f"Failed to detect title property: {e}, using 'Name'")
            self._title_property = "Name"
    
    async def _create_page(
        self,
        properties: Dict[str, Any],
        children: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """创建 Notion Page（带限流）"""
        async def _do_create():
            return await self._client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
                children=children[:100]  # Notion 限制单次最多 100 个 blocks
            )
        
        page = await rate_limiter.execute("notion", _do_create)
        
        # 如果内容超过 100 blocks，追加剩余内容
        if len(children) > 100:
            page_id = page["id"]
            for i in range(100, len(children), 100):
                batch = children[i:i+100]
                await self._append_blocks(page_id, batch)
        
        return page
    
    async def _append_blocks(self, page_id: str, blocks: List[Dict[str, Any]]):
        """追加 blocks 到 Page"""
        async def _do_append():
            return await self._client.blocks.children.append(
                block_id=page_id,
                children=blocks
            )
        
        await rate_limiter.execute("notion", _do_append)
    
    def _build_properties(self, digest: Digest) -> Dict[str, Any]:
        """构建 Page 属性"""
        date_str = digest.generated_at.strftime("%Y-%m-%d")
        
        # 统计摘要
        bullish_count = sum(
            1 for item in digest.items
            if item.analysis and item.analysis.impact_direction == "bullish"
        )
        bearish_count = sum(
            1 for item in digest.items
            if item.analysis and item.analysis.impact_direction == "bearish"
        )
        
        title = f"📰 Daily Digest - {date_str}"
        if bullish_count > 0:
            title += f" | 📈 {bullish_count}"
        if bearish_count > 0:
            title += f" | 📉 {bearish_count}"
        
        # 使用检测到的 Title 属性名
        title_prop = self._title_property or "Name"
        
        return {
            title_prop: {
                "title": [{"text": {"content": title}}]
            },
            # 如果数据库有这些属性，则设置
            # "Date": {"date": {"start": date_str}},
            # "Total Items": {"number": len(digest.items)},
            # "Bullish": {"number": bullish_count},
            # "Bearish": {"number": bearish_count},
        }
    
    def _build_content_blocks(self, digest: Digest) -> List[Dict[str, Any]]:
        """构建 Page 内容 blocks"""
        blocks = []
        
        # 标题和概览
        blocks.append(self._heading_1("📊 Daily Market News Digest"))
        
        blocks.append(self._paragraph(
            f"Generated: {digest.generated_at.strftime('%Y-%m-%d %H:%M UTC')} | "
            f"Window: {digest.window_start.strftime('%m/%d %H:%M')} - {digest.window_end.strftime('%m/%d %H:%M')} | "
            f"Items: {len(digest.items)}"
        ))
        
        blocks.append(self._divider())
        
        # 高影响力新闻
        high_impact = digest.high_impact_items
        if high_impact:
            blocks.append(self._heading_2("🔥 High Impact News"))
            
            for item in high_impact[:5]:  # 最多显示 5 条
                blocks.extend(self._build_news_item_blocks(item, show_detail=True))
            
            blocks.append(self._divider())
        
        # 按 Ticker 分组
        by_ticker = digest.by_ticker
        if by_ticker:
            blocks.append(self._heading_2("📈 News by Ticker"))
            
            for ticker, items in sorted(by_ticker.items()):
                blocks.append(self._heading_3(f"${ticker}"))
                
                for item in items[:3]:  # 每个 ticker 最多 3 条
                    blocks.extend(self._build_news_item_blocks(item, show_detail=False))
        
        # 完整列表
        if len(digest.items) > 10:
            blocks.append(self._divider())
            blocks.append(self._heading_2("📋 All News Items"))
            blocks.append(self._toggle(
                f"View all {len(digest.items)} items",
                [self._build_news_item_blocks(item, show_detail=False) for item in digest.items]
            ))
        
        return blocks
    
    def _build_news_item_blocks(
        self,
        item: DigestItem,
        show_detail: bool = False
    ) -> List[Dict[str, Any]]:
        """构建单条新闻的 blocks"""
        blocks = []
        
        news = item.news
        analysis = item.analysis
        
        # 标题行
        tickers_str = ", ".join(f"${t}" for t in news.tickers) if news.tickers else ""
        
        impact_emoji = ""
        if analysis:
            impact_map = {"bullish": "📈", "bearish": "📉", "neutral": "➖"}
            impact_emoji = impact_map.get(analysis.impact_direction, "")
        
        title_text = f"{impact_emoji} **{news.title}**"
        if tickers_str:
            title_text = f"{tickers_str} | {title_text}"
        
        blocks.append(self._bullet(title_text))
        
        if show_detail and analysis:
            # 分析详情
            detail_lines = [
                f"Type: {analysis.event_type} | Impact: {analysis.impact_direction} ({analysis.impact_horizon})",
                f"Summary: {analysis.summary}",
            ]
            
            if analysis.key_facts:
                detail_lines.append(f"Facts: {'; '.join(analysis.key_facts)}")
            
            if analysis.watch_next:
                detail_lines.append(f"Watch: {analysis.watch_next}")
            
            for line in detail_lines:
                blocks.append(self._paragraph(f"  {line}"))
        
        # 链接
        blocks.append(self._paragraph(
            f"  [{news.source}]({news.canonical_url}) | {news.published_at.strftime('%m/%d %H:%M')}"
        ))
        
        return blocks
    
    # ===== Notion Block Builders =====
    
    def _heading_1(self, text: str) -> Dict[str, Any]:
        return {
            "object": "block",
            "type": "heading_1",
            "heading_1": {"rich_text": [{"type": "text", "text": {"content": text}}]}
        }
    
    def _heading_2(self, text: str) -> Dict[str, Any]:
        return {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}
        }
    
    def _heading_3(self, text: str) -> Dict[str, Any]:
        return {
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": [{"type": "text", "text": {"content": text}}]}
        }
    
    def _paragraph(self, text: str) -> Dict[str, Any]:
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]}
        }
    
    def _bullet(self, text: str) -> Dict[str, Any]:
        return {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]}
        }
    
    def _divider(self) -> Dict[str, Any]:
        return {"object": "block", "type": "divider", "divider": {}}
    
    def _toggle(self, title: str, children: List) -> Dict[str, Any]:
        # Flatten nested lists
        flat_children = []
        for child in children:
            if isinstance(child, list):
                flat_children.extend(child)
            else:
                flat_children.append(child)
        
        return {
            "object": "block",
            "type": "toggle",
            "toggle": {
                "rich_text": [{"type": "text", "text": {"content": title}}],
                "children": flat_children[:100]  # Notion 限制
            }
        }
    
    async def close(self):
        """关闭客户端"""
        # notion-client 的 AsyncClient 不需要显式关闭
        pass
