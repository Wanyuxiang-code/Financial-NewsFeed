"""Email 输出 - 发送每日摘要邮件"""
import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional, List
from datetime import datetime
from pathlib import Path

from app.outputs.base import BaseOutput, Digest, DigestItem
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class EmailOutput(BaseOutput):
    """
    Email 输出
    
    功能：
    - 发送 HTML 格式的摘要邮件
    - 支持附件（完整 Markdown 报告）
    - 支持多种 SMTP 服务商
    
    支持的 SMTP 服务商：
    - Gmail: smtp.gmail.com:587 (需要应用专用密码)
    - Outlook: smtp.office365.com:587
    - QQ邮箱: smtp.qq.com:587 (需要授权码)
    - 163邮箱: smtp.163.com:465
    """
    
    output_name = "email"
    
    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        email_to: Optional[str] = None
    ):
        self.smtp_host = smtp_host or settings.smtp_host
        self.smtp_port = smtp_port or settings.smtp_port
        self.smtp_user = smtp_user or settings.smtp_user
        self.smtp_password = smtp_password or settings.smtp_password
        self.email_to = email_to or settings.email_to
        
        if not self.smtp_host:
            raise ValueError("SMTP host not configured")
        if not self.smtp_user:
            raise ValueError("SMTP user not configured")
        if not self.smtp_password:
            raise ValueError("SMTP password not configured")
        if not self.email_to:
            raise ValueError("Email recipient not configured")
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
    
    def _format_html_email(self, digest: Digest) -> str:
        """生成 HTML 格式的邮件内容"""
        # 统计
        bullish = sum(1 for item in digest.items if item.analysis and item.analysis.impact_direction == "bullish")
        bearish = sum(1 for item in digest.items if item.analysis and item.analysis.impact_direction == "bearish")
        neutral = len(digest.items) - bullish - bearish
        
        # 确定整体情绪
        if bullish > bearish * 2:
            sentiment_color = "#22c55e"
            sentiment_text = "偏多 BULLISH"
        elif bearish > bullish * 2:
            sentiment_color = "#ef4444"
            sentiment_text = "偏空 BEARISH"
        else:
            sentiment_color = "#6b7280"
            sentiment_text = "中性 NEUTRAL"
        
        # 按 ticker 分组
        ticker_items: dict = {}
        for item in digest.items:
            for ticker in item.news.tickers:
                if ticker not in ticker_items:
                    ticker_items[ticker] = []
                ticker_items[ticker].append(item)
        
        # 生成 ticker 卡片
        ticker_cards = []
        for ticker, items in ticker_items.items():
            t_bullish = sum(1 for i in items if i.analysis and i.analysis.impact_direction == "bullish")
            t_bearish = sum(1 for i in items if i.analysis and i.analysis.impact_direction == "bearish")
            
            if t_bullish > t_bearish:
                card_color = "#dcfce7"
                border_color = "#22c55e"
            elif t_bearish > t_bullish:
                card_color = "#fee2e2"
                border_color = "#ef4444"
            else:
                card_color = "#f3f4f6"
                border_color = "#9ca3af"
            
            # AI 摘要
            ai_summary = ""
            if ticker in digest.ticker_summaries:
                ts = digest.ticker_summaries[ticker]
                ai_summary = f'<p style="color:#4b5563;font-size:13px;margin:8px 0 0 0;">{ts.summary}</p>'
            
            # 新闻列表
            news_list = ""
            for item in items[:3]:  # 最多显示3条
                direction_icon = "📈" if item.analysis and item.analysis.impact_direction == "bullish" else "📉" if item.analysis and item.analysis.impact_direction == "bearish" else "➖"
                news_list += f'<li style="margin:4px 0;">{direction_icon} {item.news.title[:60]}{"..." if len(item.news.title) > 60 else ""}</li>'
            
            card = f'''
            <div style="background:{card_color};border-left:4px solid {border_color};padding:12px 16px;margin:12px 0;border-radius:4px;">
                <div style="font-weight:bold;font-size:16px;color:#1f2937;">${ticker}</div>
                <div style="color:#6b7280;font-size:13px;">{len(items)} 条新闻 ({t_bullish}↑ {t_bearish}↓)</div>
                {ai_summary}
                <ul style="margin:8px 0 0 0;padding-left:20px;font-size:13px;">{news_list}</ul>
            </div>
            '''
            ticker_cards.append(card)
        
        html = f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f9fafb;margin:0;padding:20px;">
    <div style="max-width:600px;margin:0 auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
        
        <!-- Header -->
        <div style="background:linear-gradient(135deg,#1e3a5f 0%,#0f172a 100%);color:white;padding:24px;text-align:center;">
            <h1 style="margin:0;font-size:24px;font-weight:600;">📰 股票新闻日报</h1>
            <p style="margin:8px 0 0 0;opacity:0.8;font-size:14px;">{digest.generated_at.strftime('%Y年%m月%d日 %H:%M')}</p>
        </div>
        
        <!-- Sentiment Banner -->
        <div style="background:{sentiment_color};color:white;padding:16px;text-align:center;">
            <div style="font-size:18px;font-weight:bold;">市场情绪: {sentiment_text}</div>
            <div style="font-size:14px;margin-top:4px;opacity:0.9;">
                📈 利好 {bullish} | 📉 利空 {bearish} | ➖ 中性 {neutral}
            </div>
        </div>
        
        <!-- Content -->
        <div style="padding:20px;">
            <h2 style="font-size:18px;color:#1f2937;margin:0 0 16px 0;padding-bottom:8px;border-bottom:2px solid #e5e7eb;">
                📊 各股分析
            </h2>
            {''.join(ticker_cards[:10])}
        </div>
        
        <!-- Footer -->
        <div style="background:#f3f4f6;padding:16px;text-align:center;font-size:12px;color:#6b7280;">
            <p style="margin:0;">由 NewsFeed AI 自动生成</p>
            <p style="margin:4px 0 0 0;">数据来源: Finnhub, SEC EDGAR | 分析: Gemini AI</p>
        </div>
        
    </div>
</body>
</html>
'''
        return html
    
    async def _send_email(
        self,
        subject: str,
        html_content: str,
        attachments: Optional[List[Path]] = None
    ) -> bool:
        """发送邮件"""
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.smtp_user
        msg['To'] = self.email_to
        
        # HTML 内容
        html_part = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(html_part)
        
        # 添加附件
        if attachments:
            for file_path in attachments:
                if file_path.exists():
                    try:
                        with open(file_path, 'rb') as f:
                            part = MIMEBase('application', 'octet-stream')
                            part.set_payload(f.read())
                            encoders.encode_base64(part)
                            part.add_header(
                                'Content-Disposition',
                                f'attachment; filename="{file_path.name}"'
                            )
                            msg.attach(part)
                    except Exception as e:
                        logger.warning(f"Failed to attach file {file_path}: {e}")
        
        # 发送邮件
        def _send():
            try:
                if self.smtp_port == 465:
                    # SSL
                    server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port)
                else:
                    # TLS
                    server = smtplib.SMTP(self.smtp_host, self.smtp_port)
                    server.starttls()
                
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.smtp_user, self.email_to, msg.as_string())
                server.quit()
                return True
            except Exception as e:
                logger.error(f"SMTP error: {e}")
                return False
        
        # 在线程中执行同步 SMTP 操作
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _send)
    
    async def deliver(self, digest: Digest) -> bool:
        """发送摘要邮件"""
        logger.info("Sending digest email...")
        
        # 生成邮件内容
        subject = f"📰 股票新闻日报 - {digest.generated_at.strftime('%Y-%m-%d')}"
        html_content = self._format_html_email(digest)
        
        # 查找最新的 Markdown 报告作为附件
        attachments = []
        digests_dir = Path(settings.watchlist_path).parent / "digests"
        if digests_dir.exists():
            md_files = sorted(digests_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
            if md_files:
                attachments.append(md_files[0])
        
        success = await self._send_email(subject, html_content, attachments)
        
        if success:
            logger.info("✅ Email sent successfully")
        else:
            logger.error("❌ Failed to send email")
        
        return success
