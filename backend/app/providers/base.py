"""AI Provider 抽象基类 - 策略模式"""
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
from pathlib import Path
import json

from pydantic import ValidationError

from app.models.schemas import AIAnalysisOutput, NewsItemCreate
from app.utils.logger import get_logger
from app.config import settings

logger = get_logger(__name__)


class AIProviderError(Exception):
    """AI Provider 错误"""
    pass


class AIAnalysisError(AIProviderError):
    """AI 分析错误"""
    pass


class BaseAIProvider(ABC):
    """
    AI 分析器抽象基类
    
    所有 AI Provider 必须实现:
    - analyze(): 分析单条新闻
    - _call_api(): 调用具体的 AI API
    
    基类提供:
    - 严格 JSON Schema 校验
    - 重试逻辑
    - Prompt 加载
    - 成本追踪
    """
    
    provider_name: str = "base"
    model_name: str = "unknown"
    prompt_version: str = "v1.0"
    
    def __init__(self):
        self._prompt_template: Optional[str] = None
    
    @property
    def prompt_template(self) -> str:
        """懒加载 Prompt 模板"""
        if self._prompt_template is None:
            self._prompt_template = self._load_prompt()
        return self._prompt_template
    
    def _load_prompt(self) -> str:
        """从文件加载 Prompt 模板"""
        prompt_path = Path(settings.prompts_dir) / f"news_analysis_{self.prompt_version}.txt"
        
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        
        # 默认 Prompt
        logger.warning(f"Prompt file not found: {prompt_path}, using default")
        return self._default_prompt()
    
    def _default_prompt(self) -> str:
        """默认 Prompt 模板"""
        return """You are a senior equity research analyst. Analyze the following news and output a JSON object.

News:
- Ticker(s): {tickers}
- Title: {title}
- Source: {source}
- Published: {published_at}
- Summary: {content}

Investment Thesis: {thesis}

Output ONLY a valid JSON object with these exact fields:
{{
  "event_type": "<earnings|guidance|regulatory|contract|product|accident|macro|rumor|other>",
  "impact_direction": "<bullish|bearish|neutral>",
  "impact_horizon": "<short|medium|long>",
  "thesis_relation": "<supports|weakens|unrelated>",
  "confidence": "<high|medium|low>",
  "confidence_reason": "<max 100 chars>",
  "summary": "<max 100 chars>",
  "key_facts": ["<fact1>", "<fact2>"],
  "watch_next": "<max 50 chars>"
}}

No markdown, no extra text. JSON only."""
    
    def format_prompt(
        self,
        news: NewsItemCreate,
        thesis: str = ""
    ) -> str:
        """格式化 Prompt"""
        tickers_str = ", ".join(news.tickers) if news.tickers else "N/A"
        published_str = news.published_at.strftime("%Y-%m-%d %H:%M UTC") if news.published_at else "Unknown"
        
        return self.prompt_template.format(
            tickers=tickers_str,
            title=news.title,
            source=news.source,
            published_at=published_str,
            content=news.summary or "(No summary available)",
            thesis=thesis or "(No specific investment thesis provided)"
        )
    
    async def analyze(
        self,
        news: NewsItemCreate,
        thesis: str = ""
    ) -> Tuple[AIAnalysisOutput, int, float]:
        """
        分析单条新闻
        
        Args:
            news: 新闻条目
            thesis: 投资论点
        
        Returns:
            (analysis_result, tokens_used, cost_usd)
        
        Raises:
            AIAnalysisError: 分析失败
        """
        prompt = self.format_prompt(news, thesis)
        
        # 第一次尝试
        try:
            raw_output, tokens, cost = await self._call_api(prompt)
            result = self._parse_and_validate(raw_output)
            return result, tokens, cost
            
        except ValidationError as e:
            logger.warning(
                "First analysis attempt failed validation, retrying with strict prompt",
                error=str(e),
                news_title=news.title[:50]
            )
            
            # 第二次尝试：使用更严格的 Prompt
            try:
                strict_prompt = self._make_strict_prompt(prompt, str(e))
                raw_output, tokens2, cost2 = await self._call_api(strict_prompt)
                result = self._parse_and_validate(raw_output)
                return result, tokens + tokens2, cost + cost2
                
            except ValidationError as e2:
                logger.error(
                    "Second analysis attempt also failed",
                    error=str(e2),
                    news_title=news.title[:50]
                )
                # 返回一个安全的默认值
                return self._fallback_result(news), tokens + tokens2, cost + cost2
            
        except Exception as e:
            logger.error(
                "AI analysis failed",
                error=str(e),
                provider=self.provider_name,
                news_title=news.title[:50]
            )
            raise AIAnalysisError(f"Analysis failed: {e}")
    
    async def batch_analyze(
        self,
        news_list: List[NewsItemCreate],
        thesis_map: dict = None
    ) -> List[Tuple[NewsItemCreate, Optional[AIAnalysisOutput], int, float]]:
        """
        批量分析新闻
        
        Args:
            news_list: 新闻列表
            thesis_map: {ticker: thesis} 映射
        
        Returns:
            [(news, analysis_or_none, tokens, cost), ...]
        """
        thesis_map = thesis_map or {}
        results = []
        
        for news in news_list:
            # 获取该新闻相关股票的投资论点
            thesis = ""
            if news.tickers:
                for ticker in news.tickers:
                    if ticker in thesis_map:
                        thesis = thesis_map[ticker]
                        break
            
            try:
                analysis, tokens, cost = await self.analyze(news, thesis)
                results.append((news, analysis, tokens, cost))
            except AIAnalysisError as e:
                logger.error(f"Batch analysis failed for news: {news.title[:50]}, error: {e}")
                results.append((news, None, 0, 0.0))
        
        return results
    
    async def generate_ticker_summary(
        self,
        ticker: str,
        company_name: str,
        news_items: List[Tuple[NewsItemCreate, Optional[AIAnalysisOutput]]],
        thesis: str = ""
    ) -> Tuple[dict, int, float]:
        """
        生成单只股票的每日汇总分析
        
        Args:
            ticker: 股票代码
            company_name: 公司名称
            news_items: 今日该股票的新闻列表 [(news, analysis), ...]
            thesis: 投资论点
            
        Returns:
            (summary_dict, tokens_used, cost_usd)
        """
        # 构建新闻列表文本
        news_list_text = []
        for i, (news, analysis) in enumerate(news_items, 1):
            item_text = f"{i}. [{news.published_at.strftime('%H:%M')}] {news.title}"
            if analysis:
                item_text += f"\n   - Impact: {analysis.impact_direction} ({analysis.event_type})"
                item_text += f"\n   - Summary: {analysis.summary}"
            news_list_text.append(item_text)
        
        news_list_str = "\n\n".join(news_list_text)
        
        # 加载汇总 prompt
        prompt_template = self._load_summary_prompt()
        prompt = prompt_template.format(
            ticker=ticker,
            company_name=company_name,
            thesis=thesis or "(No specific investment thesis)",
            news_list=news_list_str
        )
        
        logger.debug(f"Generating summary for {ticker}, prompt length: {len(prompt)}")
        
        try:
            raw_output, tokens, cost = await self._call_api(prompt)
            logger.debug(f"Summary API response for {ticker}: {raw_output[:200] if raw_output else 'None'}")
            
            if not raw_output:
                logger.warning(f"Empty API response for {ticker} summary")
                return self._fallback_summary(ticker, news_items), tokens, cost
            
            summary_data = self._parse_summary_output(raw_output)
            return summary_data, tokens, cost
            
        except Exception as e:
            import traceback
            logger.warning(f"Ticker summary generation failed for {ticker}: {type(e).__name__}: {e}")
            logger.debug(f"Traceback: {traceback.format_exc()}")
            # 返回一个基础的汇总
            return self._fallback_summary(ticker, news_items), 0, 0.0
    
    def _load_summary_prompt(self) -> str:
        """加载股票汇总 prompt 模板"""
        prompt_path = Path(settings.prompts_dir) / "ticker_summary_v1.0.txt"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        
        # 默认 prompt
        return """你是一位专业的股票分析师。基于今日关于 {ticker} ({company_name}) 的新闻，生成简洁的每日汇总。

投资论点: {thesis}

今日新闻:
{news_list}

输出 JSON 格式:
{{
  "overall_sentiment": "bullish|bearish|neutral|mixed",
  "summary": "1-2句话总结",
  "key_events": ["事件1", "事件2"],
  "thesis_impact": "对论点的影响",
  "action_suggestion": "建议行动",
  "risk_alerts": ["风险1"]
}}

只输出 JSON。"""
    
    def _parse_summary_output(self, raw_output: str) -> dict:
        """解析汇总输出"""
        cleaned = raw_output.strip()
        
        # 移除 markdown 代码块
        if "```" in cleaned:
            # 找到 JSON 部分
            import re
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', cleaned)
            if json_match:
                cleaned = json_match.group(1).strip()
            else:
                # 移除所有 ``` 标记
                cleaned = cleaned.replace("```json", "").replace("```", "").strip()
        
        # 找到 JSON 对象
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            cleaned = cleaned[start:end]
        
        logger.debug(f"Parsing summary JSON: {cleaned[:200]}")
        
        try:
            data = json.loads(cleaned)
            # 确保必要字段存在
            required = ["overall_sentiment", "summary", "key_events", "thesis_impact", "action_suggestion", "risk_alerts"]
            for field in required:
                if field not in data:
                    data[field] = "" if field in ["summary", "thesis_impact", "action_suggestion"] else []
            return data
        except json.JSONDecodeError as e:
            logger.warning(f"Summary JSON parse error: {e}, content: {cleaned[:200]}")
            return {
                "overall_sentiment": "neutral",
                "summary": "Summary generation failed",
                "key_events": [],
                "thesis_impact": "Unable to assess",
                "action_suggestion": "Continue monitoring",
                "risk_alerts": []
            }
    
    def _fallback_summary(
        self, 
        ticker: str, 
        news_items: List[Tuple[NewsItemCreate, Optional[AIAnalysisOutput]]]
    ) -> dict:
        """生成基础的汇总（AI 失败时使用）"""
        bullish = sum(1 for _, a in news_items if a and a.impact_direction == "bullish")
        bearish = sum(1 for _, a in news_items if a and a.impact_direction == "bearish")
        
        if bullish > bearish:
            sentiment = "bullish"
        elif bearish > bullish:
            sentiment = "bearish"
        else:
            sentiment = "neutral"
        
        return {
            "overall_sentiment": sentiment,
            "summary": f"Today: {len(news_items)} news items ({bullish} bullish, {bearish} bearish)",
            "key_events": [n.title[:60] for n, _ in news_items[:3]],
            "thesis_impact": "Requires manual assessment",
            "action_suggestion": "Continue monitoring",
            "risk_alerts": []
        }
    
    def _parse_and_validate(self, raw_output: str) -> AIAnalysisOutput:
        """解析并验证 AI 输出"""
        # 清理输出（去除可能的 markdown 代码块标记）
        cleaned = raw_output.strip()
        
        # 记录原始输出用于调试
        logger.debug(f"Raw AI output (first 500 chars): {cleaned[:500]}")
        
        if cleaned.startswith("```"):
            # 去除 markdown 代码块
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        
        # 尝试找到 JSON 对象
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            cleaned = cleaned[start:end]
        else:
            logger.warning(f"No JSON object found in output: {cleaned[:200]}")
        
        # 解析 JSON
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error: {e}, content: {cleaned[:300]}")
            raise ValidationError.from_exception_data(
                "AIAnalysisOutput",
                [{"type": "json_invalid", "msg": f"Invalid JSON: {e}"}]
            )
        
        # 检查是否是错误响应
        if "error" in data and isinstance(data.get("error"), dict):
            error_msg = data.get("error", {}).get("message", str(data))
            logger.warning(f"API returned error response: {error_msg}")
            raise ValidationError.from_exception_data(
                "AIAnalysisOutput", 
                [{"type": "api_error", "msg": f"API error: {error_msg}"}]
            )
        
        # Pydantic 验证
        return AIAnalysisOutput.model_validate(data)
    
    def _make_strict_prompt(self, original_prompt: str, error_msg: str) -> str:
        """生成更严格的 Prompt（用于重试）"""
        return f"""{original_prompt}

IMPORTANT: Your previous response had validation errors: {error_msg}

Please ensure:
1. Output is ONLY valid JSON, no markdown or extra text
2. event_type must be exactly one of: earnings, guidance, regulatory, contract, product, accident, macro, rumor, other
3. impact_direction must be exactly one of: bullish, bearish, neutral
4. impact_horizon must be exactly one of: short, medium, long
5. thesis_relation must be exactly one of: supports, weakens, unrelated
6. confidence must be exactly one of: high, medium, low
7. summary must be 100 characters or less
8. key_facts must be an array with at most 3 items
9. watch_next must be 50 characters or less"""
    
    def _fallback_result(self, news: NewsItemCreate) -> AIAnalysisOutput:
        """返回安全的默认分析结果"""
        return AIAnalysisOutput(
            event_type="other",
            impact_direction="neutral",
            impact_horizon="short",
            thesis_relation="unrelated",
            confidence="low",
            confidence_reason="Analysis failed, using fallback",
            summary=news.title[:100] if news.title else "No summary",
            key_facts=[],
            watch_next=""
        )
    
    @abstractmethod
    async def _call_api(self, prompt: str) -> Tuple[str, int, float]:
        """
        调用具体的 AI API
        
        Args:
            prompt: 完整的 prompt
        
        Returns:
            (raw_output, tokens_used, cost_usd)
        """
        pass
    
    async def close(self):
        """关闭资源（子类可重写）"""
        pass
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
