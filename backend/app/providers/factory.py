"""AI Provider 工厂 - 根据配置创建对应的 Provider"""
from typing import Dict, Type, Optional

from app.providers.base import BaseAIProvider, AIProviderError
from app.utils.logger import get_logger
from app.config import settings

logger = get_logger(__name__)


class AIProviderFactory:
    """
    AI Provider 工厂模式
    
    根据配置或参数创建对应的 AI Provider 实例
    """
    
    _providers: Dict[str, Type[BaseAIProvider]] = {}
    
    @classmethod
    def register(cls, name: str, provider_class: Type[BaseAIProvider]):
        """注册 Provider"""
        cls._providers[name] = provider_class
        logger.debug(f"Registered AI provider: {name}")
    
    @classmethod
    def create(
        cls,
        provider_name: Optional[str] = None,
        **kwargs
    ) -> BaseAIProvider:
        """
        创建 AI Provider 实例
        
        Args:
            provider_name: Provider 名称，不指定则使用配置中的默认值
            **kwargs: 传递给 Provider 构造函数的参数
        
        Returns:
            BaseAIProvider 实例
        
        Raises:
            AIProviderError: 未知的 Provider
        """
        name = provider_name or settings.ai_provider
        
        if name not in cls._providers:
            raise AIProviderError(
                f"Unknown AI provider: {name}. "
                f"Available: {list(cls._providers.keys())}"
            )
        
        provider_class = cls._providers[name]
        
        try:
            provider = provider_class(**kwargs)
            logger.info(f"Created AI provider: {name}")
            return provider
        except Exception as e:
            raise AIProviderError(f"Failed to create provider {name}: {e}")
    
    @classmethod
    def list_providers(cls) -> list:
        """列出所有已注册的 Provider"""
        return list(cls._providers.keys())


# 注册默认 Providers
def _register_default_providers():
    """注册默认的 AI Providers"""
    try:
        from app.providers.gemini import GeminiProvider
        AIProviderFactory.register("gemini", GeminiProvider)
    except Exception as e:
        logger.debug(f"Gemini provider not available: {e}")
    
    try:
        from app.providers.openai import OpenAIProvider
        AIProviderFactory.register("openai", OpenAIProvider)
    except Exception as e:
        logger.debug(f"OpenAI provider not available: {e}")


# 自动注册
_register_default_providers()


def get_ai_provider(provider_name: Optional[str] = None, **kwargs) -> BaseAIProvider:
    """
    获取 AI Provider 的便捷函数
    
    Usage:
        provider = get_ai_provider()  # 使用默认配置
        provider = get_ai_provider("openai")  # 指定 provider
        provider = get_ai_provider("gemini", api_key="xxx")  # 自定义参数
    """
    return AIProviderFactory.create(provider_name, **kwargs)
