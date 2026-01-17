"""Gemini AI Provider - Google GenAI SDK (新版)"""
from typing import Tuple, Optional

from app.providers.base import BaseAIProvider, AIProviderError
from app.utils.logger import get_logger
from app.config import settings

logger = get_logger(__name__)

# 延迟导入 Google GenAI SDK
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logger.warning("google-genai not installed, Gemini provider unavailable")


class GeminiProvider(BaseAIProvider):
    """
    Google Gemini AI Provider (使用新版 google-genai SDK)
    
    支持:
    - Gemini 2.0 Flash
    - Gemini Pro
    
    定价 (2024):
    - Gemini Pro: $0.00025/1K input, $0.0005/1K output
    """
    
    provider_name = "gemini"
    
    # Gemini 定价 (USD per 1K tokens)
    PRICE_INPUT = 0.00025
    PRICE_OUTPUT = 0.0005
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        super().__init__()
        
        if not GENAI_AVAILABLE:
            raise AIProviderError("google-genai package not installed. Run: pip install google-genai")
        
        self.api_key = api_key or settings.gemini_api_key
        self.model_name = model or settings.gemini_model
        self.api_endpoint = settings.gemini_api_endpoint
        
        if not self.api_key:
            raise AIProviderError("Gemini API key not configured")
        
        # 创建客户端
        http_options = None
        if self.api_endpoint:
            # 使用自定义 API 代理
            http_options = types.HttpOptions(base_url=self.api_endpoint)
            logger.info(f"Using custom API endpoint: {self.api_endpoint}")
        
        self._client = genai.Client(
            api_key=self.api_key,
            http_options=http_options
        )
        
        # 生成配置
        self._generation_config = types.GenerateContentConfig(
            temperature=0.1,  # 低温度，更确定性
            top_p=0.95,
            top_k=40,
            max_output_tokens=8192,  # 避免截断
        )
        
        logger.info(f"GeminiProvider initialized with model: {self.model_name}")
    
    async def _call_api(self, prompt: str) -> Tuple[str, int, float]:
        """
        调用 Gemini API
        
        Returns:
            (raw_output, tokens_used, cost_usd)
        """
        import asyncio
        
        def _do_call_sync():
            # 使用同步方法
            return self._client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=self._generation_config,
            )
        
        # 在线程池中执行同步调用
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, _do_call_sync)
        
        # 提取文本
        if not response.text:
            raise AIProviderError("Gemini returned empty response")
        
        raw_output = response.text
        
        # 计算 token 和成本
        tokens_input = 0
        tokens_output = 0
        
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            tokens_input = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
            tokens_output = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0
        else:
            # 估算 token（粗略：4 字符 ≈ 1 token）
            tokens_input = len(prompt) // 4
            tokens_output = len(raw_output) // 4
        
        total_tokens = tokens_input + tokens_output
        cost_usd = (tokens_input * self.PRICE_INPUT + tokens_output * self.PRICE_OUTPUT) / 1000
        
        logger.debug(
            "Gemini API call completed",
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cost_usd=f"${cost_usd:.6f}"
        )
        
        return raw_output, total_tokens, cost_usd
