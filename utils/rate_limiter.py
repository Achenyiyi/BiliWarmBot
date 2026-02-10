"""
限流器模块 - 防止触发风控

原理：
- 令牌桶算法：以固定速率生成令牌，请求需要消耗令牌
- 当令牌不足时，请求被限流
- 支持突发流量（桶容量）

使用场景：
- B站API调用频率限制
- DeepSeek API调用频率限制
- 防止触发平台风控
"""

import asyncio
import time
from typing import Optional
from dataclasses import dataclass
from functools import wraps


@dataclass
class RateLimitConfig:
    """限流配置"""
    rate: float = 1.0       # 每秒生成令牌数
    burst: int = 5        # 桶容量（突发流量）
    

class RateLimiter:
    """
    令牌桶限流器
    
    使用示例：
        limiter = RateLimiter(rate=2.0, burst=10)  # 每秒2个，最多突发10个
        
        @limiter
        async def api_call():
            # API调用
            pass
    """
    
    _instances: dict = {}
    
    def __new__(cls, name: str, config: RateLimitConfig = None):
        """单例模式"""
        if name not in cls._instances:
            instance = super().__new__(cls)
            instance._initialized = False
            cls._instances[name] = instance
        return cls._instances[name]
    
    def __init__(self, name: str, config: RateLimitConfig = None):
        if self._initialized:
            return
            
        self.name = name
        self.config = config or RateLimitConfig()
        self.tokens = self.config.burst  # 初始满桶
        self.last_update = time.time()
        self._lock = asyncio.Lock()
        self._initialized = True
    
    async def acquire(self, tokens: int = 1, timeout: Optional[float] = None) -> bool:
        """
        获取令牌
        
        Args:
            tokens: 需要的令牌数
            timeout: 等待超时时间（秒），None表示一直等待
            
        Returns:
            是否成功获取
        """
        start_time = time.time()
        
        while True:
            async with self._lock:
                self._add_tokens()
                
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True
                
                # 计算需要等待的时间
                needed = tokens - self.tokens
                wait_time = needed / self.config.rate
                
                if timeout is not None:
                    elapsed = time.time() - start_time
                    if elapsed + wait_time > timeout:
                        return False
            
            # 在锁外等待
            await asyncio.sleep(min(wait_time, 0.1))
    
    def _add_tokens(self):
        """根据时间流逝添加令牌"""
        now = time.time()
        elapsed = now - self.last_update
        self.last_update = now
        
        # 添加令牌，不超过桶容量
        self.tokens = min(
            self.config.burst,
            self.tokens + elapsed * self.config.rate
        )
    
    async def call(self, func, *args, **kwargs):
        """
        在限流保护下执行函数
        
        Args:
            func: 要执行的函数
            *args, **kwargs: 函数参数
            
        Returns:
            函数返回值
            
        Raises:
            RateLimitExceeded: 限流超时
        """
        if not await self.acquire():
            raise RateLimitExceeded(f"限流器 {self.name} 获取令牌超时")
        
        return await func(*args, **kwargs)
    
    def __call__(self, func):
        """装饰器用法"""
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await self.call(func, *args, **kwargs)
        return wrapper
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "name": self.name,
            "tokens": self.tokens,
            "rate": self.config.rate,
            "burst": self.config.burst
        }


class RateLimitExceeded(Exception):
    """限流异常"""
    pass


# 预定义的限流器
# B站API：保守设置，避免风控
bilibili_limiter = RateLimiter("bilibili", RateLimitConfig(rate=0.5, burst=3))  # 每秒0.5个

# DeepSeek API：较宽松
deepseek_limiter = RateLimiter("deepseek", RateLimitConfig(rate=2.0, burst=10))

# 评论发送：非常保守
comment_limiter = RateLimiter("comment", RateLimitConfig(rate=0.2, burst=2))  # 每5秒1个
