"""
温暖陪伴机器人 - 主入口模块（柯南优化版）

基于 Bilibili API 和 DeepSeek AI 的情感陪伴机器人，
自动发现需要情感支持的用户，并给予温暖的回复。

优化点：
1. 统一初始化管理 - 所有组件异步初始化
2. 优雅关闭 - 确保资源正确释放
3. 信号处理 - 支持Ctrl+C优雅退出
4. 健康检查 - 启动前验证关键依赖

运行环境：Python 3.8+
依赖包：见 requirements.txt
"""

import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional

# 添加项目路径到 Python 路径，确保模块导入正常
sys.path.insert(0, str(Path(__file__).parent))

from core import WarmBot


class Application:
    """
    应用生命周期管理器
    
    职责：
    1. 管理WarmBot实例生命周期
    2. 处理系统信号（Ctrl+C）
    3. 确保资源正确释放
    4. 提供健康检查
    """
    
    def __init__(self):
        self.bot: Optional[WarmBot] = None
        self.shutdown_event = asyncio.Event()
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """设置信号处理器"""
        # Windows支持SIGINT，Unix还支持SIGTERM
        signal.signal(signal.SIGINT, self._signal_handler)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """信号处理回调"""
        print(f"\n\n收到信号 {signum}，正在优雅关闭...")
        self.shutdown_event.set()
    
    async def initialize(self) -> bool:
        """
        异步初始化应用
        
        Returns:
            是否初始化成功
        """
        try:
            print("🔧 正在初始化...")
            
            # 创建机器人实例
            self.bot = WarmBot()
            
            # 异步初始化（如果WarmBot实现了initialize方法）
            if hasattr(self.bot, 'initialize') and asyncio.iscoroutinefunction(self.bot.initialize):
                await self.bot.initialize()
            
            print("✅ 初始化完成")
            return True
            
        except Exception as e:
            print(f"❌ 初始化失败: {e}")
            return False
    
    async def run(self):
        """
        运行主循环
        
        同时监听：
        1. 机器人主循环
        2. 关闭信号
        """
        if not self.bot:
            print("❌ 机器人未初始化")
            return
        
        # 创建两个任务：机器人运行 和 信号监听
        bot_task = asyncio.create_task(self.bot.run())
        signal_task = asyncio.create_task(self.shutdown_event.wait())
        
        # 等待任一任务完成
        done, pending = await asyncio.wait(
            [bot_task, signal_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # 取消剩余任务
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # 优雅关闭
        await self.shutdown()
    
    async def shutdown(self):
        """优雅关闭应用"""
        print("\n🛑 正在关闭...")
        
        if self.bot:
            self.bot.stop()
            
            # 等待清理完成
            if hasattr(self.bot, 'cleanup') and asyncio.iscoroutinefunction(self.bot.cleanup):
                await self.bot.cleanup()
        
        print("👋 已安全退出，再见！")


def print_banner():
    """打印启动横幅"""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                    🌟 温暖陪伴机器人 🌟                       ║
╠══════════════════════════════════════════════════════════════╣
║  自动识别需要安慰的评论，给予温暖回复                          ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)


async def main():
    """主函数 - 程序入口"""
    print_banner()
    
    # 创建应用实例
    app = Application()
    
    # 初始化
    if not await app.initialize():
        sys.exit(1)
    
    # 运行
    try:
        await app.run()
    except Exception as e:
        print(f"\n❌ 运行时错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Windows 平台事件循环策略配置
    # 解决 Windows 上 asyncio 的默认事件循环限制
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # 启动异步主循环
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # 这个异常通常被信号处理器处理，这里是最后一道防线
        print("\n\n程序被中断")
        sys.exit(0)
