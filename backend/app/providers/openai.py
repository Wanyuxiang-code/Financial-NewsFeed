"""OpenAI Provider - GPT-4, GPT-4o-mini"""
from typing import Tuple, Optional

from app.providers.base import BaseAIProvider, AIProviderError
from app.utils.rate_limiter import rate_limiter
from app.utils.logger import get_logger
from app.config import settings

logger = get_logger(__name__)

# 延迟导入 OpenAI SDK
try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("openai package not installed, OpenAI provider unavailable")


class OpenAIProvider(BaseAIProvider):
    """
    OpenAI Provider
    
    支持:
    - GPT-4o
    - GPT-4o-mini
    - GPT-4-turbo
    
    定价 (2024, per 1K tokens):
    - GPT-4o: $5/1M input, $15/1M output
    - GPT-4o-mini: $0.15/1M input, $0.6/1M output
    """
    
    provider_name = "openai"
    
    # 定价表 (USD per 1M tokens)
    PRICING = {
        "gpt-4o": {"input": 5.0, "output": 15.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.6},
        "gpt-4-turbo": {"input": 10.0, "output": 30.0},
        "gpt-4": {"input": 30.0, "output": 60.0},
        "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
    }
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        super().__init__()
        
        if not OPENAI_AVAILABLE:
            raise AIProviderError("openai package not installed")
        
        self.api_key = api_key or settings.openai_api_key
        self.model_name = model or settings.openai_model
        
        if not self.api_key:
            raise AIProviderError("OpenAI API key not configured")
        
        self._client = AsyncOpenAI(api_key=self.api_key)
        
        logger.info(f"OpenAIProvider initialized with model: {self.model_name}")
    
    async def _call_api(self, prompt: str) -> Tuple[str, int, float]:
        """
        调用 OpenAI API
        
        Returns:
            (raw_output, tokens_used, cost_usd)
        """
        async def _do_call():
            response = await self._client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a senior equity research analyst. Always respond with valid JSON only, no markdown or extra text."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,
                max_tokens=1024,
                response_format={"type": "json_object"}  # 强制 JSON 输出
            )
            return response
        
        # 使用限流器
        response = await rate_limiter.execute("openai", _do_call)
        
        # 提取文本
        if not response.choices:
            raise AIProviderError("OpenAI returned no choices")
        
        raw_output = response.choices[0].message.content
        
        # 计算 token 和成本
        tokens_input = response.usage.prompt_tokens if response.usage else 0
        tokens_output = response.usage.completion_tokens if response.usage else 0
        total_tokens = tokens_input + tokens_output
        
        # 获取定价
        pricing = self.PRICING.get(self.model_name, self.PRICING["gpt-4o-mini"])
        cost_usd = (
            tokens_input * pricing["input"] / 1_000_000 +
            tokens_output * pricing["output"] / 1_000_000
        )
        
        logger.debug(
            "OpenAI API call completed",
            model=self.model_name,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cost_usd=f"${cost_usd:.6f}"
        )
        
        return raw_output, total_tokens, cost_usd
    
    async def close(self):
        """关闭客户端"""
        if self._client:
            await self._client.close()
