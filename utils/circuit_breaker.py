"""
熔断器模块 - 防止级联故障

原理：
- 当API连续失败次数超过阈值，熔断器打开
- 熔断期间直接返回错误，不再调用API
- 经过冷却时间后，进入半开状态，尝试恢复
- 成功则关闭，失败则重新熔断

状态转换：
CLOSED (正常) --失败次数超限--> OPEN (熔断)
OPEN --冷却时间到--> HALF_OPEN (半开)
HALF_OPEN --成功--> CLOSED
HALF_OPEN --失败--> OPEN
"""

import asyncio
import time
from enum import Enum
from typing import Optional, Callable, Any
from dataclasses import dataclass
from functools import wraps


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"       # 正常状态，允许请求
    OPEN = "open"          # 熔断状态，拒绝请求
    HALF_OPEN = "half_open" # 半开状态，试探性允许


@dataclass
class CircuitBreakerConfig:
    """熔断器配置"""
    failure_threshold: int = 5      # 失败次数阈值
    recovery_timeout: float = 60.0  # 冷却时间（秒）
    half_open_max_calls: int = 3    # 半开状态最大试探次数


class CircuitBreaker:
    """
    熔断器 - 防止级联故障
    
    使用示例：
        breaker = CircuitBreaker("bilibili_api")
        
        @breaker
        async def call_bilibili_api():
            # API调用
            pass
    """
    
    _instances: dict = {}
    
    def __new__(cls, name: str, config: CircuitBreakerConfig = None):
        """单例模式，同名熔断器共享状态"""
        if name not in cls._instances:
            instance = super().__new__(cls)
            instance._initialized = False
            cls._instances[name] = instance
        return cls._instances[name]
    
    def __init__(self, name: str, config: CircuitBreakerConfig = None):
        if self._initialized:
            return
            
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.half_open_calls = 0
        self._lock = asyncio.Lock()
        self._initialized = True
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        在熔断器保护下执行函数
        
        Args:
            func: 要执行的异步函数
            *args, **kwargs: 函数参数
            
        Returns:
            函数返回值
            
        Raises:
            CircuitBreakerOpen: 熔断器打开时
            Exception: 函数执行异常
        """
        async with self._lock:
            await self._update_state()
            
            if self.state == CircuitState.OPEN:
                raise CircuitBreakerOpen(f"熔断器 {self.name} 已打开")
            
            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls >= self.config.half_open_max_calls:
                    raise CircuitBreakerOpen(f"熔断器 {self.name} 半开状态限制")
                self.half_open_calls += 1
        
        # 执行函数（在锁外执行，避免阻塞）
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise
    
    async def _update_state(self):
        """更新熔断器状态"""
        if self.state == CircuitState.OPEN:
            # 检查是否过了冷却时间
            if self.last_failure_time and \
               time.time() - self.last_failure_time >= self.config.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
                print(f"🔓 熔断器 {self.name} 进入半开状态")
    
    async def _on_success(self):
        """成功回调"""
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                # 连续成功足够次数，关闭熔断器
                if self.success_count >= 2:
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    self.success_count = 0
                    self.half_open_calls = 0
                    print(f"✅ 熔断器 {self.name} 已关闭")
            else:
                self.failure_count = 0
    
    async def _on_failure(self):
        """失败回调"""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.state == CircuitState.HALF_OPEN:
                # 半开状态失败，重新熔断
                self.state = CircuitState.OPEN
                self.half_open_calls = 0
                print(f"🔥 熔断器 {self.name} 重新熔断")
            elif self.failure_count >= self.config.failure_threshold:
                # 达到阈值，打开熔断器
                self.state = CircuitState.OPEN
                print(f"🔥 熔断器 {self.name} 已打开（连续失败{self.failure_count}次）")
    
    def __call__(self, func: Callable) -> Callable:
        """装饰器用法"""
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await self.call(func, *args, **kwargs)
        return wrapper
    
    @property
    def is_open(self) -> bool:
        """熔断器是否打开"""
        return self.state == CircuitState.OPEN
    
    @property
    def is_closed(self) -> bool:
        """熔断器是否关闭"""
        return self.state == CircuitState.CLOSED
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "half_open_calls": self.half_open_calls,
            "last_failure": self.last_failure_time
        }


class CircuitBreakerOpen(Exception):
    """熔断器打开异常"""
    pass


# 预定义的熔断器实例
bilibili_breaker = CircuitBreaker("bilibili_api", CircuitBreakerConfig(
    failure_threshold=3,      # B站API容易风控，阈值设低
    recovery_timeout=300.0    # 5分钟冷却
))

deepseek_breaker = CircuitBreaker("deepseek_api", CircuitBreakerConfig(
    failure_threshold=5,
    recovery_timeout=60.0
))
