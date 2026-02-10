"""
重试处理器 - 处理瞬时失败

原理：
- 指数退避：每次重试等待时间指数增长
- 抖动：添加随机因子避免惊群效应
- 可重试异常：只重试特定类型的异常

使用场景：
- 网络超时
- 服务暂时不可用
- 限流导致的失败
"""

import asyncio
import random
import time
from typing import Optional, List, Type, Callable, Any
from dataclasses import dataclass
from functools import wraps


@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 3              # 最大重试次数
    base_delay: float = 1.0           # 基础延迟（秒）
    max_delay: float = 60.0           # 最大延迟（秒）
    exponential_base: float = 2.0     # 指数基数
    jitter: bool = True               # 是否添加抖动
    retryable_exceptions: List[Type[Exception]] = None
    
    def __post_init__(self):
        if self.retryable_exceptions is None:
            # 默认重试这些异常
            self.retryable_exceptions = [
                ConnectionError,
                TimeoutError,
                asyncio.TimeoutError,
            ]


class RetryHandler:
    """
    重试处理器
    
    使用示例：
        config = RetryConfig(max_retries=3, base_delay=1.0)
        retry = RetryHandler(config)
        
        @retry
        async def unstable_api():
            # 可能失败的API调用
            pass
    """
    
    def __init__(self, config: RetryConfig = None, name: str = "default"):
        self.config = config or RetryConfig()
        self.name = name
        self.retry_count = 0
        self.success_count = 0
        self.failure_count = 0
    
    async def execute(self, func: Callable, *args, **kwargs) -> Any:
        """
        执行函数，失败时自动重试
        
        Args:
            func: 要执行的异步函数
            *args, **kwargs: 函数参数
            
        Returns:
            函数返回值
            
        Raises:
            Exception: 重试耗尽后仍失败
        """
        last_exception = None
        
        for attempt in range(self.config.max_retries + 1):
            try:
                result = await func(*args, **kwargs)
                self.success_count += 1
                
                if attempt > 0:
                    print(f"✅ {self.name} 第{attempt}次重试成功")
                
                return result
                
            except Exception as e:
                last_exception = e
                
                # 检查是否应该重试
                if not self._should_retry(e):
                    raise
                
                if attempt < self.config.max_retries:
                    delay = self._calculate_delay(attempt)
                    self.retry_count += 1
                    
                    print(f"⚠️  {self.name} 尝试{attempt + 1}/{self.config.max_retries + 1}失败: {str(e)[:50]}...")
                    print(f"    {delay:.1f}秒后重试...")
                    
                    await asyncio.sleep(delay)
                else:
                    self.failure_count += 1
                    print(f"❌ {self.name} 重试耗尽，最终失败")
        
        # 重试耗尽
        raise last_exception
    
    def _should_retry(self, exception: Exception) -> bool:
        """检查异常是否应该重试"""
        # 检查异常类型
        for exc_type in self.config.retryable_exceptions:
            if isinstance(exception, exc_type):
                return True
        
        # 检查异常消息（针对特定错误码）
        error_msg = str(exception).lower()
        retryable_keywords = [
            'timeout', 'connection', 'temporary', 'unavailable',
            'rate limit', 'too many requests', '503', '502', '504'
        ]
        
        for keyword in retryable_keywords:
            if keyword in error_msg:
                return True
        
        return False
    
    def _calculate_delay(self, attempt: int) -> float:
        """计算重试延迟（指数退避 + 抖动）"""
        # 指数退避
        delay = self.config.base_delay * (self.config.exponential_base ** attempt)
        
        # 限制最大延迟
        delay = min(delay, self.config.max_delay)
        
        # 添加抖动（±25%）
        if self.config.jitter:
            jitter = delay * 0.25
            delay = delay + random.uniform(-jitter, jitter)
        
        return max(0.1, delay)  # 最小0.1秒
    
    def __call__(self, func: Callable) -> Callable:
        """装饰器用法"""
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await self.execute(func, *args, **kwargs)
        return wrapper
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        total = self.success_count + self.failure_count
        success_rate = self.success_count / total if total > 0 else 0
        
        return {
            "name": self.name,
            "retry_count": self.retry_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": f"{success_rate:.1%}"
        }


# 预定义的重试配置
# B站API重试（较保守）
bilibili_retry = RetryHandler(RetryConfig(
    max_retries=2,
    base_delay=2.0,
    max_delay=30.0
), name="bilibili")

# DeepSeek API重试
deepseek_retry = RetryHandler(RetryConfig(
    max_retries=3,
    base_delay=1.0,
    max_delay=10.0
), name="deepseek")

# 通用网络请求重试
general_retry = RetryHandler(RetryConfig(
    max_retries=3,
    base_delay=1.0,
    max_delay=60.0
), name="general")
