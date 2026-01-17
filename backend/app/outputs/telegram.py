"""Telegram Bot 输出 - 推送每日摘要到 Telegram"""
import asyncio
from typing import Optional
from datetime import datetime
import aiohttp

from app.outputs.base import BaseOutput, Digest, DigestItem
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class TelegramOutput(BaseOutput):
    """
    Telegram Bot 输出
    
    功能：
    - 推送摘要概览
    - 发送重要新闻提醒
    - 支持 Markdown 格式
    
    设置步骤：
    1. 在 Telegram 中找 @BotFather
    2. 发送 /newbot 创建机器人
    3. 获取 Bot Token
    4. 获取你的 Chat ID（可以用 @userinfobot）
    """
    
    output_name = "telegram"
    
    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None
    ):
        self.bot_token = bot_token or settings.telegram_bot_token
        self.chat_id = chat_id or settings.telegram_chat_id
        
        if not self.bot_token:
            raise ValueError("Telegram bot token not configured")
        if not self.chat_id:
            raise ValueError("Telegram chat ID not configured")
        
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()
    
    async def _send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_preview: bool = True
    ) -> bool:
        """发送消息到 Telegram"""
        if not self._session:
            self._session = aiohttp.ClientSession()
        
        url = f"{self.api_base}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_preview
        }
        
        try:
            async with self._session.post(url, json=payload) as resp:
                if resp.status == 200:
                    return True
                else:
                    error = await resp.text()
                    logger.error(f"Telegram API error: {resp.status} - {error}")
                    return False
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    async def _send_photo(
        self,
        photo_path: str,
        caption: str = ""
    ) -> bool:
        """发送图片到 Telegram"""
        if not self._session:
            self._session = aiohttp.ClientSession()
        
        url = f"{self.api_base}/sendPhoto"
        
        try:
            with open(photo_path, 'rb') as photo:
                data = aiohttp.FormData()
                data.add_field('chat_id', self.chat_id)
                data.add_field('photo', photo, filename=photo_path.split('/')[-1])
                if caption:
                    data.add_field('caption', caption[:1024])  # Telegram 限制
                    data.add_field('parse_mode', 'HTML')
                
                async with self._session.post(url, data=data) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error(f"Failed to send Telegram photo: {e}")
            return False
    
    def _format_digest_message(self, digest: Digest) -> str:
        """格式化摘要消息（HTML 格式）"""
        # 统计
        bullish = sum(1 for item in digest.items if item.analysis and item.analysis.impact_direction == "bullish")
        bearish = sum(1 for item in digest.items if item.analysis and item.analysis.impact_direction == "bearish")
        neutral = len(digest.items) - bullish - bearish
        
        # 确定整体情绪
        if bullish > bearish * 2:
            sentiment_emoji = "🟢"
            sentiment_text = "偏多"
        elif bearish > bullish * 2:
            sentiment_emoji = "🔴"
            sentiment_text = "偏空"
        else:
            sentiment_emoji = "⚪"
            sentiment_text = "中性"
        
        # 构建消息
        lines = [
            f"<b>📰 股票新闻日报</b>",
            f"<i>{digest.generated_at.strftime('%Y-%m-%d %H:%M')}</i>",
            "",
            f"{sentiment_emoji} <b>市场情绪: {sentiment_text}</b>",
            f"📈 利好: {bullish} | 📉 利空: {bearish} | ➖ 中性: {neutral}",
            "",
            "<b>📊 各股要点:</b>",
        ]
        
        # 按 ticker 分组
        ticker_items: dict = {}
        for item in digest.items:
            for ticker in item.news.tickers:
                if ticker not in ticker_items:
                    ticker_items[ticker] = []
                ticker_items[ticker].append(item)
        
        # 添加每个 ticker 的摘要
        for ticker, items in list(ticker_items.items())[:8]:  # 限制数量
            # 统计该 ticker 的情绪
            t_bullish = sum(1 for i in items if i.analysis and i.analysis.impact_direction == "bullish")
            t_bearish = sum(1 for i in items if i.analysis and i.analysis.impact_direction == "bearish")
            
            if t_bullish > t_bearish:
                emoji = "🟢"
            elif t_bearish > t_bullish:
                emoji = "🔴"
            else:
                emoji = "⚪"
            
            # 获取 AI 摘要
            summary_text = ""
            if ticker in digest.ticker_summaries:
                ts = digest.ticker_summaries[ticker]
                summary_text = f"\n   └ {ts.summary[:80]}..." if len(ts.summary) > 80 else f"\n   └ {ts.summary}"
            
            lines.append(f"{emoji} <b>${ticker}</b>: {len(items)} 条新闻 ({t_bullish}↑ {t_bearish}↓){summary_text}")
        
        # 添加重要新闻
        important_items = [
            item for item in digest.items 
            if item.analysis and item.analysis.confidence >= 0.7
        ][:5]
        
        if important_items:
            lines.append("")
            lines.append("<b>🔥 重要新闻:</b>")
            for item in important_items:
                direction = "📈" if item.analysis.impact_direction == "bullish" else "📉" if item.analysis.impact_direction == "bearish" else "➖"
                title = item.news.title[:50] + "..." if len(item.news.title) > 50 else item.news.title
                lines.append(f"{direction} {title}")
        
        lines.append("")
        lines.append("<i>💡 完整报告已保存到本地</i>")
        
        return "\n".join(lines)
    
    async def deliver(self, digest: Digest) -> bool:
        """推送摘要到 Telegram"""
        logger.info("Sending digest to Telegram...")
        
        # 发送主消息
        message = self._format_digest_message(digest)
        success = await self._send_message(message)
        
        if success:
            logger.info("✅ Telegram notification sent successfully")
        else:
            logger.error("❌ Failed to send Telegram notification")
        
        return success
