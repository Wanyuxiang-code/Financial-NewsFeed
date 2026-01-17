"""统一限流器 + 重试策略 - 所有外部 API 调用都走这个中间层"""
import asyncio
import random
from typing import Any, Callable, Dict, Optional, TypeVar
from dataclasses import dataclass
from functools import wraps

import httpx
from aiolimiter import AsyncLimiter
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    RetryError
)

from app.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


@dataclass
class RateLimitConfig:
    """单个 API 的限流配置"""
    rate: int  # 请求数
    per: float  # 时间窗口（秒）
    user_agent_required: bool = False
    user_agent: Optional[str] = None


class RateLimitError(Exception):
    """限流错误"""
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class RateLimiter:
    """
    统一限流器 - 支持不同 API 的配置
    
    特性:
    - 令牌桶限流
    - 指数退避 + jitter
    - Retry-After 支持
    - 最多重试 3 次
    """
    
    # 各 API 的限流配置
    CONFIGS: Dict[str, RateLimitConfig] = {
        "sec": RateLimitConfig(
            rate=10,
            per=1.0,
            user_agent_required=True,
            user_agent="NewsFeed/1.0 (contact@example.com)"
        ),
        "finnhub": RateLimitConfig(rate=60, per=60.0),
        "notion": RateLimitConfig(rate=3, per=1.0),
        "gemini": RateLimitConfig(rate=60, per=60.0),
        "openai": RateLimitConfig(rate=60, per=60.0),
        "claude": RateLimitConfig(rate=60, per=60.0),
    }
    
    def __init__(self):
        self._limiters: Dict[str, AsyncLimiter] = {}
        self._init_limiters()
    
    def _init_limiters(self):
        """初始化各 API 的限流器"""
        for api_name, config in self.CONFIGS.items():
            self._limiters[api_name] = AsyncLimiter(config.rate, config.per)
    
    def get_config(self, api_name: str) -> RateLimitConfig:
        """获取 API 配置"""
        if api_name not in self.CONFIGS:
            raise ValueError(f"Unknown API: {api_name}")
        return self.CONFIGS[api_name]
    
    def update_config(self, api_name: str, config: RateLimitConfig):
        """更新 API 配置（运行时动态调整）"""
        self.CONFIGS[api_name] = config
        self._limiters[api_name] = AsyncLimiter(config.rate, config.per)
    
    async def acquire(self, api_name: str):
        """获取令牌（阻塞直到可用）"""
        if api_name not in self._limiters:
            raise ValueError(f"Unknown API: {api_name}")
        await self._limiters[api_name].acquire()
    
    async def execute(
        self,
        api_name: str,
        func: Callable[..., T],
        *args,
        max_retries: int = 3,
        **kwargs
    ) -> T:
        """
        带限流、指数退避、Retry-After 支持的执行器
        
        Args:
            api_name: API 名称（用于选择限流配置）
            func: 要执行的异步函数
            *args, **kwargs: 传递给 func 的参数
            max_retries: 最大重试次数
        
        Returns:
            func 的返回值
        
        Raises:
            RateLimitError: 超过最大重试次数
            Exception: func 抛出的其他异常
        """
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                # 等待令牌
                await self.acquire(api_name)
                
                # 执行函数
                result = await func(*args, **kwargs)
                return result
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    # 读取 Retry-After 头
                    retry_after = self._parse_retry_after(e.response)
                    
                    if attempt < max_retries:
                        # 指数退避 + jitter
                        wait_time = self._calculate_backoff(attempt, retry_after)
                        logger.warning(
                            "Rate limited, retrying",
                            api=api_name,
                            attempt=attempt + 1,
                            wait_seconds=wait_time,
                            retry_after=retry_after
                        )
                        await asyncio.sleep(wait_time)
                        last_error = e
                    else:
                        raise RateLimitError(
                            f"Rate limit exceeded for {api_name} after {max_retries} retries",
                            retry_after=retry_after
                        )
                elif e.response.status_code in (500, 502, 503, 504):
                    # 服务器错误，重试
                    if attempt < max_retries:
                        wait_time = self._calculate_backoff(attempt)
                        logger.warning(
                            "Server error, retrying",
                            api=api_name,
                            status_code=e.response.status_code,
                            attempt=attempt + 1,
                            wait_seconds=wait_time
                        )
                        await asyncio.sleep(wait_time)
                        last_error = e
                    else:
                        raise
                else:
                    # 其他 HTTP 错误，不重试
                    raise
                    
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                # 网络错误，重试
                if attempt < max_retries:
                    wait_time = self._calculate_backoff(attempt)
                    logger.warning(
                        "Network error, retrying",
                        api=api_name,
                        error=str(e),
                        attempt=attempt + 1,
                        wait_seconds=wait_time
                    )
                    await asyncio.sleep(wait_time)
                    last_error = e
                else:
                    raise
        
        # 不应该到达这里
        if last_error:
            raise last_error
        raise RuntimeError("Unexpected state in rate limiter")
    
    def _parse_retry_after(self, response: httpx.Response) -> Optional[float]:
        """解析 Retry-After 头"""
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                # 可能是日期格式，暂时忽略
                pass
        return None
    
    def _calculate_backoff(
        self,
        attempt: int,
        retry_after: Optional[float] = None
    ) -> float:
        """
        计算退避时间：指数退避 + jitter
        
        基础等待时间: 2^attempt 秒
        Jitter: ±25%
        如果有 Retry-After，使用较大值
        """
        base_wait = 2 ** attempt
        jitter = random.uniform(0.75, 1.25)
        wait_time = base_wait * jitter
        
        if retry_after:
            wait_time = max(wait_time, retry_after)
        
        # 最大等待 60 秒
        return min(wait_time, 60.0)


# 全局限流器实例
rate_limiter = RateLimiter()


def rate_limited(api_name: str, max_retries: int = 3):
    """
    装饰器：为函数添加限流和重试
    
    Usage:
        @rate_limited("finnhub")
        async def fetch_news(ticker: str) -> List[dict]:
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await rate_limiter.execute(
                api_name,
                func,
                *args,
                max_retries=max_retries,
                **kwargs
            )
        return wrapper
    return decorator


class RateLimitedClient:
    """
    带限流的 HTTP 客户端基类
    
    子类只需要指定 api_name 和 base_url
    """
    
    api_name: str = "default"
    base_url: str = ""
    timeout: float = 30.0
    
    def __init__(self):
        self.config = rate_limiter.get_config(self.api_name)
        self._client: Optional[httpx.AsyncClient] = None
    
    @property
    def client(self) -> httpx.AsyncClient:
        """懒加载 HTTP 客户端"""
        if self._client is None:
            headers = {}
            if self.config.user_agent_required and self.config.user_agent:
                headers["User-Agent"] = self.config.user_agent
            
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers=headers,
            )
        return self._client
    
    async def close(self):
        """关闭客户端"""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def get(self, path: str, **kwargs) -> httpx.Response:
        """带限流的 GET 请求"""
        async def _do_request():
            response = await self.client.get(path, **kwargs)
            response.raise_for_status()
            return response
        
        return await rate_limiter.execute(self.api_name, _do_request)
    
    async def post(self, path: str, **kwargs) -> httpx.Response:
        """带限流的 POST 请求"""
        async def _do_request():
            response = await self.client.post(path, **kwargs)
            response.raise_for_status()
            return response
        
        return await rate_limiter.execute(self.api_name, _do_request)
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
