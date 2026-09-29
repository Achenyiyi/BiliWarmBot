"""
温暖陪伴机器人核心模块

功能：
1. 防护层集成（熔断器、限流器、重试机制）
2. 资源管理（上下文管理器）
3. 健康检查
4. 优雅降级

核心流程：
1. 检查需要跟进的对话
2. 搜索新视频
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from bilibili_api import video, comment
from bilibili_api.comment import CommentResourceType, OrderType, Comment
from bilibili_api.utils.network import Credential
from bilibili_api.utils.aid_bvid_transformer import bvid2aid

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    BILIBILI_COOKIE, NEGATIVE_KEYWORDS,
    SEARCH_CONFIG, COMMENT_CONFIG, LOG_FILE, ERROR_LOG_FILE,
    SCENE_PRIORITY, EMERGENCY_LOG, JEV_API_KEY, JEV_FILTER_CONFIG,
    DEEPSEEK_GENERATION_CONFIG, BILIBILI_GUARD_STATE,
    BILIBILI_MIN_REQUEST_INTERVAL, BILIBILI_COOLDOWN_SECONDS
)
from config.bot_config import PERFORMANCE_CONFIG, CONVERSATION_CONFIG

from database.db_manager import DatabaseManager
from modules.deepseek_analyzer import DeepSeekAnalyzer
from modules import VideoContentExtractor, CommentInteractor
from modules.comment_context import CommentContextFetcher
from modules.jev_filter import JevCommentFilter

from utils.circuit_breaker import bilibili_breaker, deepseek_breaker
from utils.rate_limiter import bilibili_limiter, deepseek_limiter, comment_limiter
from utils.retry_handler import bilibili_retry, deepseek_retry
from utils.bilibili_guard import (
    BilibiliRiskError,
    BilibiliNonRetryableError,
    install_bilibili_guard,
)


class WarmBot:
    """
    B站温暖陪伴机器人
    
    功能：
    - 防护层保护（熔断、限流、重试）
    - 资源管理
    - 健康检查
    - 优雅降级
    """
    
    def __init__(self):
        self.logger = self._setup_logging()
        self.credential = self._init_credential()
        
        # 组件初始化（延迟到initialize）
        self.db: Optional[DatabaseManager] = None
        self.analyzer: Optional[DeepSeekAnalyzer] = None
        self.video_extractor: Optional[VideoContentExtractor] = None
        self.comment_interactor: Optional[CommentInteractor] = None
        self.comment_context_fetcher: Optional[CommentContextFetcher] = None
        self.jev_filter: Optional[JevCommentFilter] = None
        
        # 机器人自己的UID（用于排除自己的回复）
        self.bot_uid: Optional[str] = None
        
        self.running = False
        self._print_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._initialized = False
        
        # 统计
        self._stats = {
            'videos_processed': 0,
            'replies_processed': 0,
            'replies_sent': 0,
            'api_calls': 0,
            'start_time': None,
            'errors': []
        }
    
    async def _print(self, text: str):
        """线程安全的打印输出"""
        async with self._print_lock:
            print(text)
    
    async def initialize(self) -> bool:
        """
        异步初始化所有组件
        
        Returns:
            是否初始化成功
        """
        try:
            self.logger.info("🔧 开始初始化组件...")
            install_bilibili_guard(BILIBILI_GUARD_STATE, BILIBILI_MIN_REQUEST_INTERVAL,
                                   BILIBILI_COOLDOWN_SECONDS)
            
            # 1. 初始化数据库
            self.db = DatabaseManager()
            await self._init_database()
            
            # 2. 初始化AI分析器
            self.analyzer = DeepSeekAnalyzer()
            
            # 3. 初始化视频提取器
            self.video_extractor = VideoContentExtractor(self.credential)
            
            # 4. 初始化评论交互器
            self.comment_interactor = CommentInteractor(self.credential, self.db)
            
            # 5. 初始化评论区上下文获取器
            self.comment_context_fetcher = CommentContextFetcher(self.credential)

            if not JEV_API_KEY:
                raise ValueError("Jev 判断需要 TYPESAFE_API_KEY")
            self.jev_filter = JevCommentFilter(JEV_API_KEY)

            # 6. 健康检查
            if not await self._health_check():
                self.logger.error("❌ 健康检查失败")
                return False
            
            self._initialized = True
            self.logger.info("✅ 所有组件初始化完成")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 初始化失败: {e}")
            self._stats['errors'].append(f"初始化: {e}")
            return False
    
    async def cleanup(self):
        """清理资源"""
        self.logger.info("🧹 开始清理资源...")
        if self.jev_filter:
            await self.jev_filter.close()
        
        # 关闭分析器（释放HTTP客户端）
        if self.analyzer and hasattr(self.analyzer, 'close'):
            try:
                await self.analyzer.close()
                self.logger.info("   AI分析器已关闭")
            except Exception as e:
                self.logger.warning(f"   关闭AI分析器失败: {e}")
        
        # 关闭数据库连接
        if self.db:
            try:
                await self.db.close()
                self.logger.info("   数据库已关闭")
            except Exception as e:
                self.logger.warning(f"   关闭数据库失败: {e}")
        
        self.logger.info("✅ 资源清理完成")
    
    async def _init_database(self):
        """初始化数据库"""
        # 数据库已经在__init__中初始化，这里可以添加额外检查
        pass
    
    async def _health_check(self) -> bool:
        """
        健康检查 - 验证关键依赖
        
        Returns:
            是否通过健康检查
        """
        self.logger.info("🏥 执行健康检查...")
        checks = []
        
        # 1. 检查B站凭据
        try:
            # 简单验证凭据格式
            if not self.credential.sessdata:
                checks.append(("B站凭据", False, "SESSDATA为空"))
            else:
                checks.append(("B站凭据", True, "格式正确"))
        except Exception as e:
            checks.append(("B站凭据", False, str(e)))
        
        # 2. 检查数据库连接
        try:
            # 尝试简单查询
            test_conv = await self.db.get_replied_conversations_to_check()
            checks.append(("数据库", True, "连接正常"))
        except Exception as e:
            checks.append(("数据库", False, str(e)))
        
        # 3. 检查AI分析器
        try:
            # 检查API密钥
            if hasattr(self.analyzer, 'api_key') and self.analyzer.api_key:
                checks.append(("AI分析器", True, "配置正确"))
            else:
                checks.append(("AI分析器", False, "API密钥未配置"))
        except Exception as e:
            checks.append(("AI分析器", False, str(e)))
        
        # 打印检查结果
        for name, status, msg in checks:
            icon = "✅" if status else "❌"
            self.logger.info(f"   {icon} {name}: {msg}")
        
        # 关键检查必须通过
        critical_checks = ["B站凭据", "数据库"]
        all_passed = all(
            status for name, status, _ in checks 
            if name in critical_checks
        )
        
        return all_passed
    
    def _setup_logging(self) -> logging.Logger:
        """配置日志"""
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 文件处理器
        file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        
        # 错误处理器
        error_handler = logging.FileHandler(ERROR_LOG_FILE, encoding='utf-8')
        error_handler.setFormatter(formatter)
        error_handler.setLevel(logging.ERROR)
        
        # 控制台处理器（只显示重要信息）
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.WARNING)
        
        # 根日志器
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.handlers = []
        root_logger.addHandler(file_handler)
        root_logger.addHandler(error_handler)
        root_logger.addHandler(console_handler)
        
        # 降低第三方库日志级别
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("bilibili_api").setLevel(logging.WARNING)
        
        return logging.getLogger(__name__)
    
    def _init_credential(self) -> Credential:
        """初始化B站API凭据"""
        cookies = {}
        for item in BILIBILI_COOKIE.split(';'):
            if '=' in item:
                key, value = item.strip().split('=', 1)
                cookies[key] = value
        
        # 保存机器人自己的UID
        self.bot_uid = cookies.get('DedeUserID')
        
        # 使用构造函数直接创建 Credential
        credential = Credential(
            sessdata=cookies.get('SESSDATA'),
            bili_jct=cookies.get('bili_jct'),
            buvid3=cookies.get('buvid3'),
            dedeuserid=self.bot_uid,
            ac_time_value=cookies.get('ac_time_value')
        )
        
        return credential
    
    # ========== 主流程 ==========
    
    async def run(self):
        """运行主循环"""
        if not self._initialized:
            self.logger.error("❌ 机器人未初始化，请先调用initialize()")
            return
        
        self.running = True
        
        while self.running:
            try:
                await self.run_cycle()
                
                # 等待下一个周期（配置是分钟，转换为秒）
                interval_minutes = PERFORMANCE_CONFIG.get('scan_interval_minutes', 5)
                interval = interval_minutes * 60
                await self._print(f"\n⏳ {interval_minutes}分钟后进入下一周期...")
                
                # 分段等待，便于快速响应停止信号
                for _ in range(interval):
                    if not self.running:
                        break
                    await asyncio.sleep(1)
                    
            except Exception as e:
                self.logger.error(f"运行周期异常: {e}")
                self._stats['errors'].append(str(e))
                await asyncio.sleep(60)  # 异常后等待1分钟
    
    async def run_cycle(self):
        """运行一个完整周期"""
        self._stats['start_time'] = time.time()
        
        await self._print(f"\n{'='*60}")
        await self._print("🚀 温暖陪伴机器人启动")
        await self._print(f"{'='*60}")
        
        try:
            # 1. 检查需要跟进的对话（兜底）- 只检查 replied 状态
            await self._check_pending_conversations()
            await self._retry_failed_comments()
            # 2. 搜索并处理新视频
            await self._process_new_videos()
        except BilibiliRiskError as exc:
            self.logger.error("Bilibili 风控触发，本轮立即停止: %s", exc)
            await self._print(f"   ⛔ B站风控触发，本轮已停止: {exc}")
            self._stats['errors'].append(f"Bilibili 风控: {exc}")
            return
        
        # 3. 打印统计
        await self._print_stats()

    async def _retry_failed_comments(self):
        """重试先前生成失败的候选评论。"""
        for item in await self.db.get_comment_retries():
            await self._process_comment(
                item['bvid'], item['title'], json.loads(item['comment_json'])
            )
    
    def stop(self):
        """停止机器人"""
        self.running = False
        self.logger.info("🛑 收到停止信号")
    
    # ========== 对话处理 ==========
    
    async def _continue_conversation(self, conv_id: int, bvid: str, root_id: int,
                                    parent_id: int, username: str, content: str,
                                    messages: List[Dict], check_count: int = 0):
        """继续对话 - 生成回复"""
        await self._print(f"   💬 {username}: {content[:40]}...")
        
        video_info = await self.db.get_tracked_video(bvid)
        video_title = video_info['title'] if video_info else "未知视频"
        
        # 获取视频内容摘要（使用完整逻辑：AI总结 -> 字幕 -> 标题+简介）
        video_summary = ""
        try:
            video_content = await self.video_extractor.extract_video_content(bvid)
            if video_content and video_content.get('summary'):
                video_summary = video_content['summary']
                source_desc = video_content.get('source_desc', '未知来源')
                await self._print(f"      📹 已获取视频内容 ({source_desc})")
        except Exception as e:
            self.logger.debug(f"获取视频内容失败: {e}")
        
        comments_context = ""
        try:
            if self.comment_context_fetcher:
                comments_context = await self.comment_context_fetcher.fetch_video_comments_context(
                    bvid=bvid,
                    max_comments=COMMENT_CONFIG.get('comments_context_count', 50),
                    include_replies=True
                )
                if comments_context:
                    await self._print(f"      📋 已获取评论区上下文 ({len(comments_context)} 字符)")
        except Exception as e:
            self.logger.debug(f"获取评论区上下文失败: {e}")
        
        # 计算真实对话轮数（user消息的数量）
        current_round = sum(1 for msg in messages if msg.get('role') == 'user')
        
        should_continue = await self._should_continue_with_protection(
            user_reply=content,
            conversation_history=messages,
            current_round=current_round,
            max_rounds=CONVERSATION_CONFIG['max_check_count']
        )

        latest_rpid = messages[-1].get('rpid') if messages else None
        
        if not should_continue.get('should_reply'):
            await self.db.add_message(conv_id, 'user', content, rpid=latest_rpid)
            reason = should_continue.get('reason', '未知原因')
            await self._print(f"      🔚 AI判断无需继续对话: {reason}")
            await self.db.update_conversation_status(
                conv_id=conv_id,
                status='closed',
                close_reason='user_ended'
            )
            return
        
        try:
            reply_text = await self._generate_follow_up_with_protection(
                video_title=video_title,
                video_summary=video_summary,
                conversation_history=messages,
                comments_context=comments_context
            )
            
            if not reply_text:
                await self._print(f"      AI未生成回复")
                return
            
            sent = await self._send_reply_with_protection(
                bvid=bvid, root_id=root_id, parent_id=parent_id,
                content=reply_text, conv_id=conv_id,
                username=username, original_content=content,
                user_rpid=latest_rpid
            )
            if not sent:
                await self.db.update_conversation_status(
                    conv_id=conv_id,
                    status='replied',
                    next_check_at=datetime.now() + timedelta(minutes=10)
                )
            
        except Exception as e:
            self.logger.error(f"生成回复失败: {e}")
            self._stats['errors'].append(f"生成回复: {e}")
    
    async def _should_continue_with_protection(self, user_reply: str,
                                                conversation_history: list,
                                                current_round: int,
                                                max_rounds: int) -> dict:
        """用 Jev 判断是否继续对话。"""
        if current_round >= max_rounds:
            return {"should_reply": False, "reason": "达到最大对话轮数"}
        result = await self.jev_filter.decide_continue(user_reply, conversation_history)
        self.logger.info("Jev 续聊判断 reply=%s confidence=%.3f model=%s",
                         result['should_reply'], result['confidence'], result['model'])
        return {"should_reply": result['should_reply'],
                "reason": "用户继续交流" if result['should_reply'] else "用户结束或仅简短回应"}
    
    async def _generate_follow_up_with_protection(self, video_title: str, video_summary: str,
                                                   conversation_history: list,
                                                   comments_context: str = "") -> Optional[str]:
        """在防护下调用AI生成后续回复"""
        try:
            await deepseek_limiter.acquire()
            return await deepseek_breaker.call(
                deepseek_retry.execute,
                self.analyzer.generate_follow_up_reply,
                video_title=video_title,
                video_summary=video_summary,
                conversation_history=conversation_history,
                comments_context=comments_context
            )
        except Exception as e:
            self.logger.error(f"AI生成后续回复失败: {e}")
            return None
    
    async def _send_reply_with_protection(self, bvid: str, root_id: int, 
                                         parent_id: int, content: str, conv_id: int,
                                         username: str = "", original_content: str = "",
                                         user_rpid=None):
        """
        在防护下发送回复
        
        使用：
        - 严格的限流（评论发送频率限制）
        - 熔断器
        """
        try:
            # 发送必须串行；DeepSeek 可以并发生成，但 B 站评论不能并发提交。
            send_lock = getattr(self, '_send_lock', None)
            if send_lock is None:
                send_lock = asyncio.Lock()
            async with send_lock:
                await comment_limiter.acquire()
                await bilibili_breaker.call(
                    self._send_reply_internal,
                    bvid, root_id, parent_id, content, conv_id,
                    username, original_content, user_rpid
                )
            return True
        except BilibiliRiskError:
            raise
        except BilibiliNonRetryableError as e:
            self.logger.warning("评论发送不可重试 bvid=%s: %s", bvid, e)
            raise
        except Exception as e:
            self.logger.error(f"发送回复失败: {e}")
            self._stats['errors'].append(f"发送回复: {e}")
            return False
    
    async def _send_reply_internal(self, bvid: str, root_id: int, parent_id: int,
                                   content: str, conv_id: int,
                                   username: str = "", original_content: str = "",
                                   user_rpid=None):
        """内部发送回复方法"""
        try:
            # 使用 CommentInteractor 发送回复，支持回复格式
            rpid = await self.comment_interactor.send_reply(
                oid=bvid2aid(bvid),
                content=content,
                root=root_id,
                parent=parent_id,
                reply_to_uname=username,
                reply_to_content=original_content
            )
            
            if not rpid:
                raise Exception("发送回复失败，未获取到评论ID")
            
            # 记录机器人评论到数据库（用于后续判断是否是回复机器人）
            await self.db.record_bot_comment(
                comment_id=rpid,
                bvid=bvid,
                root_id=root_id,
                content=content
            )
            
            # 更新对话状态
            await self.db.update_conversation_status(
                conv_id=conv_id,
                status='replied',
                next_check_at=datetime.now() + timedelta(hours=1)
            )

            # 记录消息
            if user_rpid is not None:
                await self.db.add_message(conv_id, 'user', original_content, rpid=user_rpid)
            await self.db.add_message(conv_id, 'bot', content, rpid=rpid)
            
            # 显示回复信息（包含用户名和原评论）
            if username and original_content:
                await self._print(f"      ✅ 已回复 @{username}: 「{original_content}」 → 「{content}」")
            else:
                await self._print(f"      ✅ 已回复: {content}")
            self._stats['replies_sent'] += 1
            
        except Exception as e:
            raise  # 抛出异常让重试机制处理
    
    # ========== 第二层：兜底检查 ==========
    
    async def _check_pending_conversations(self):
        """检查需要跟进的对话（兜底机制）"""
        await self._print("\n📋 检查待跟进对话...")
        
        try:
            conversations = await self.db.get_replied_conversations_to_check()
            
            if not conversations:
                await self._print("   没有需要跟进的对话")
                return
            
            await self._print(f"   发现 {len(conversations)} 个对话需要检查")

            # 各对话相互独立：并发拉取子评论，并发执行 Jev 续聊判断，
            # 由信号量控制对 B 站和 AI 服务的瞬时压力。
            concurrency = max(1, int(CONVERSATION_CONFIG.get('check_concurrency', 10)))
            check_limit = asyncio.Semaphore(concurrency)

            async def check_one(conv):
                async with check_limit:
                    try:
                        await self._check_conversation_updates(conv)
                    except BilibiliRiskError:
                        raise
                    except Exception as exc:
                        self.logger.error("检查对话 %s 失败: %s", conv.get('id'), exc)
                        self._stats['errors'].append(f"检查对话 {conv.get('id')}: {exc}")

            results = await asyncio.gather(*(check_one(conv) for conv in conversations),
                                           return_exceptions=True)
            for conv, result in zip(conversations, results):
                if isinstance(result, BilibiliRiskError):
                    raise result
                if isinstance(result, Exception):
                    self.logger.error("待跟进任务异常退出，对话 %s: %s", conv.get('id'), result)
                
        except BilibiliRiskError:
            raise
        except Exception as e:
            self.logger.error(f"检查对话失败: {e}")
            self._stats['errors'].append(f"检查对话: {e}")
    
    async def _check_conversation_updates(self, conv: Dict):
        """检查单个对话的更新"""
        bvid = conv['bvid']
        root_id = conv['root_comment_id']
        
        try:
            # 1. 检查对话是否已超时（24小时）
            last_reply_time = conv.get('last_reply_at') or conv.get('updated_at') or conv.get('created_at')
            if last_reply_time:
                if isinstance(last_reply_time, str):
                    last_reply_time = datetime.fromisoformat(last_reply_time.replace('Z', '+00:00'))
                    # 如果时间是 naive（无时区），假设为本地时间
                    if last_reply_time.tzinfo is None:
                        from datetime import timezone
                        # 将 UTC 时间转换为本地时间（created_at 存储的是 UTC）
                        last_reply_time = last_reply_time.replace(tzinfo=timezone.utc).astimezone(tz=None).replace(tzinfo=None)
                hours_since_last_reply = (datetime.now() - last_reply_time).total_seconds() / 3600
                
                if hours_since_last_reply >= CONVERSATION_CONFIG['conversation_retention_hours']:
                    await self.db.update_conversation_status(
                        conv_id=conv['id'],
                        status='closed',
                        close_reason='timeout'
                    )
                    await self._print(f"   🔒 对话 {conv['id']}: 超过24小时未回复，已关闭")
                    return
            
            # 2. 使用 Comment 类获取该评论下的子评论（回复）
            c = Comment(
                oid=bvid2aid(bvid),
                type_=CommentResourceType.VIDEO,
                rpid=root_id,
                credential=self.credential
            )
            sub_comments_result = await c.get_sub_comments(page_index=1, page_size=20)
            
            # 3. 解析子评论，检查是否有用户的新回复
            sub_replies = (sub_comments_result.get('replies') or []) if isinstance(sub_comments_result, dict) else []
            
            # 获取已记录的消息ID，避免重复处理
            existing_messages = await self.db.get_conversation_messages(conv['id'])
            if existing_messages is None:
                existing_messages = []
            # 统一转为字符串进行比较，避免 int/str 类型不匹配
            existing_rpics = {str(msg.get('rpid')) for msg in existing_messages if msg.get('rpid')}
            
            # 获取机器人最后一条回复的rpid，用于判断用户是否回复了机器人
            bot_messages = [msg for msg in existing_messages if msg.get('role') == 'bot' and msg.get('rpid')]
            last_bot_rpid = str(bot_messages[-1].get('rpid')) if bot_messages else None
            manual_intervention_detected = False
            
            # 找出用户的新回复（只处理直接回复机器人的）
            new_user_replies = []
            for reply in sub_replies:
                rpid = reply.get('rpid')
                rpid_str = str(rpid) if rpid else None
                if rpid_str and rpid_str not in existing_rpics:
                    user_mid = (reply.get('member') or {}).get('mid')
                    user_mid_str = str(user_mid) if user_mid else None
                    
                    # 排除机器人自己的回复
                    if user_mid_str and self.bot_uid and user_mid_str == str(self.bot_uid):
                        reply_content = (reply.get('content') or {}).get('message', '')
                        # 以数据库中的评论 ID 为准；正文标记可能被 B 站清理。
                        if await self.db.is_bot_comment(rpid):
                            await self.db.add_message(conv['id'], 'bot', reply_content, rpid=rpid_str)
                        else:
                            # 人工回复：只要历史中已有机器人评论记录，就暂停自动跟进。
                            has_ai_reply = False
                            for msg in bot_messages:
                                if await self.db.is_bot_comment(msg['rpid']):
                                    has_ai_reply = True
                                    break
                            if has_ai_reply:
                                # AI参与过的对话，人工干预后暂停
                                await self.db.update_conversation_status(
                                    conv_id=conv['id'],
                                    status='paused',
                                    close_reason='manual_intervention'
                                )
                                manual_intervention_detected = True
                                await self._print(f"   👤 对话 {conv['id']}: 检测到人工干预，已暂停")
                            else:
                                # 用户自己主动发起的对话，AI直接忽略（关闭）
                                await self.db.update_conversation_status(
                                    conv_id=conv['id'],
                                    status='closed',
                                    close_reason='manual_initiated'
                                )
                                await self._print(f"   👤 对话 {conv['id']}: 检测到人工主动回复，AI忽略")
                        continue
                    
                    # 只处理目标用户直接回复机器人的评论
                    if user_mid_str and user_mid_str == str(conv.get('user_mid')):
                        parent_id_raw = reply.get('parent', 0)
                        # 提前获取用户名用于日志
                        reply_username = (reply.get('member') or {}).get('uname', '用户')
                        # 检查是否直接回复机器人的最后一条消息
                        if last_bot_rpid and str(parent_id_raw) == last_bot_rpid:
                            new_user_replies.append({
                                'reply': reply,
                                'rpid_str': rpid_str,
                                'parent_id': int(parent_id_raw) if parent_id_raw else root_id
                            })
                        else:
                            # 用户回复了其他人（包括自己），记录但不处理
                            self.logger.debug(f"用户 {reply_username} 回复了非机器人消息(parent={parent_id_raw})，忽略")
                    # 其他用户的回复直接忽略
            
            if manual_intervention_detected:
                # 同一批子评论可能同时包含用户回复和人工接管；人工接管优先，
                # 本轮不再触发 Jev/DeepSeek，也不发送自动回复。
                for item in new_user_replies:
                    reply = item['reply']
                    await self.db.add_message(
                        conv['id'], 'user',
                        (reply.get('content') or {}).get('message', ''),
                        rpid=item['rpid_str']
                    )
                return

            if new_user_replies:
                latest_item = new_user_replies[-1]
                latest_reply = latest_item['reply']
                rpid_str = latest_item['rpid_str']
                parent_id = latest_item['parent_id']
                username = (latest_reply.get('member') or {}).get('uname', '用户')
                content = (latest_reply.get('content') or {}).get('message', '')
                
                # 检查对话状态，如果是paused且用户有新回复，判断回复对象
                current_status = conv.get('status', '')
                if current_status == 'paused':
                    # 获取用户回复的parent_id，找到被回复的消息
                    user_reply_parent_id = str(parent_id)
                    replied_to_bot = False
                    
                    # 在子评论中查找被回复的消息
                    for reply in sub_replies:
                        if str(reply.get('rpid')) == user_reply_parent_id:
                            parent_content = (reply.get('content') or {}).get('message', '')
                            if await self.db.is_bot_comment(user_reply_parent_id):
                                replied_to_bot = True
                            break
                    
                    if replied_to_bot:
                        # 用户回复的是AI消息，重新激活
                        await self._print(f"   🔄 对话 {conv['id']}: 暂停状态检测到用户回复AI，重新激活")
                        await self.db.update_conversation_status(
                            conv_id=conv['id'],
                            status='replied'
                        )
                    else:
                        # 用户回复的是人工消息，保持暂停
                        await self._print(f"   ⏸️ 对话 {conv['id']}: 用户回复人工消息，保持暂停")
                        # 记录用户回复但不激活AI
                        await self.db.add_message(conv['id'], 'user', content, rpid=rpid_str)
                        # 更新检查次数和下次检查时间
                        check_count = conv.get('check_count', 0) + 1
                        paused_config = CONVERSATION_CONFIG['paused_config']
                        next_interval = paused_config['check_interval_minutes']
                        next_check_at = datetime.now() + timedelta(minutes=next_interval)
                        await self.db.update_conversation_status(
                            conv_id=conv['id'],
                            status='paused',
                            next_check_at=next_check_at,
                            check_count=check_count
                        )
                        return
                
                await self._print(f"   💬 对话 {conv['id']}: 收到 {len(new_user_replies)} 条新回复")
                
                messages = list(await self.db.get_conversation_messages(conv['id']) or [])
                messages.append({'role': 'user', 'content': content, 'rpid': rpid_str})
                
                await self._continue_conversation(
                    conv['id'], bvid, root_id, parent_id,
                    username, content, messages,
                    check_count=conv.get('check_count', 0)
                )
                return
            
            check_count = conv.get('check_count', 0) + 1
            current_status = conv.get('status', 'replied')
            
            # 根据状态使用不同的配置
            if current_status == 'paused':
                # 暂停状态使用独立配置
                paused_config = CONVERSATION_CONFIG['paused_config']
                max_checks = paused_config['max_check_count']
                
                if check_count >= max_checks:
                    await self.db.update_conversation_status(
                        conv_id=conv['id'],
                        status='closed',
                        check_count=check_count,
                        close_reason='paused_max_checks'
                    )
                    await self._print(f"   🔒 对话 {conv['id']}: 暂停状态检查次数达上限({max_checks}次)，已关闭")
                    return
                
                # 暂停状态使用固定间隔（6小时）
                next_interval = paused_config['check_interval_minutes']
                next_check_at = datetime.now() + timedelta(minutes=next_interval)
                
                await self.db.update_conversation_status(
                    conv_id=conv['id'],
                    status='paused',  # 保持paused状态
                    next_check_at=next_check_at,
                    check_count=check_count
                )
                await self._print(f"   ⏳ 对话 {conv['id']}: 暂停状态无新回复，{next_interval}分钟后再次检查(第{check_count}次)")
            else:
                # replied状态使用原有逻辑
                max_checks = CONVERSATION_CONFIG['max_check_count']
                
                if check_count >= max_checks:
                    await self.db.update_conversation_status(
                        conv_id=conv['id'],
                        status='closed',
                        check_count=check_count,
                        close_reason='max_checks_reached'
                    )
                    await self._print(f"   🔒 对话 {conv['id']}: 检查次数达上限({max_checks}次)，已关闭")
                    return
                
                base_minutes = CONVERSATION_CONFIG['backoff_base_minutes']
                next_interval = base_minutes * (2 ** (check_count - 1))
                max_interval = CONVERSATION_CONFIG['max_check_interval_minutes']
                next_interval = min(next_interval, max_interval)
                
                next_check_at = datetime.now() + timedelta(minutes=next_interval)
                
                await self.db.update_conversation_status(
                    conv_id=conv['id'],
                    status='replied',
                    next_check_at=next_check_at,
                    check_count=check_count
                )
                await self._print(f"   ⏳ 对话 {conv['id']}: 无新回复，{next_interval}分钟后再次检查(第{check_count}次)")
            
        except Exception as e:
            error_msg = str(e)
            # B站会用 12006/12022 表示根评论已不存在。
            if '12006' in error_msg or '12022' in error_msg or '已经被删除' in error_msg or '没有该评论' in error_msg:
                self.logger.warning(f"对话 {conv['id']} 的根评论已被删除，关闭对话")
                await self.db.close_conversation(conv['id'])
                await self._print(f"   🗑️ 对话 {conv['id']}: 原评论已被删除，已关闭")
            # 检查是否是评论功能已关闭的错误 (12002)
            elif '12002' in error_msg or '评论功能已关闭' in error_msg:
                self.logger.warning(f"对话 {conv['id']} 的视频评论功能已关闭，关闭对话")
                await self.db.update_conversation_status(
                    conv_id=conv['id'],
                    status='closed',
                    close_reason='comments_disabled'
                )
                await self._print(f"   🔒 对话 {conv['id']}: 视频评论功能已关闭，关闭对话")
            else:
                import traceback
                self.logger.error(f"检查对话 {conv['id']} 失败: {e}")
                self.logger.error(f"堆栈: {traceback.format_exc()}")
    
    # ========== 第三层：新视频处理 ==========
    
    async def _process_new_videos(self):
        """搜索并处理新视频"""
        await self._print("\n🔍 搜索新视频...")
        
        try:
            # 使用防护层搜索（搜索阶段已实时去重）
            videos = await self._search_with_protection()
            
            if not videos:
                await self._print("   没有发现新视频")
                return
            
            await self._print(f"   发现 {len(videos)} 个新视频")
            
            for video_info in videos[:SEARCH_CONFIG.get('max_videos_per_scan', 5)]:
                await self._process_video(video_info)
                await asyncio.sleep(3)
                
        except BilibiliRiskError:
            raise
        except Exception as e:
            self.logger.error(f"处理新视频失败: {e}")
            self._stats['errors'].append(f"处理新视频: {e}")
    
    async def _search_with_protection(self) -> List[Dict]:
        """在防护下搜索视频"""
        try:
            await bilibili_limiter.acquire()
            
            return await bilibili_breaker.call(
                bilibili_retry.execute,
                self.comment_interactor.search_negative_videos,
                keywords=NEGATIVE_KEYWORDS,
                scene_priority=SCENE_PRIORITY,
                max_results=SEARCH_CONFIG.get('max_videos_per_scan', 5),
                time_range_days=SEARCH_CONFIG.get('time_range_days', 7)
            )
        except BilibiliRiskError:
            raise
        except Exception as e:
            self.logger.error(f"搜索视频失败: {e}")
            return []
    
    async def _process_video(self, video_info: Dict):
        """处理单个视频"""
        bvid = video_info['bvid']
        title = video_info['title']
        
        await self._print(f"\n📺 [{bvid}] {title[:50]}...")
        
        # 追踪视频（搜索阶段已过滤已处理视频，这里直接记录）
        await self.db.track_video(bvid, title)
        processed = 0
        replies_count = 0
        
        # 获取评论
        try:
            await bilibili_limiter.acquire()
            
            comments_data = video_info.get('_initial_comments')
            if comments_data is None:
                comments_data = await comment.get_comments(
                    oid=bvid2aid(bvid),
                    type_=CommentResourceType.VIDEO,
                    order=OrderType.TIME,
                    credential=self.credential
                )
            
            # 检查评论数据是否为空
            if not comments_data:
                await self._print(f"   视频暂无评论")
                return
            
            # 获取总评论数并更新视频记录
            total_comments = comments_data.get('page', {}).get('count', 0)
            if total_comments > 0:
                await self.db.track_video(bvid, title, total_comments)
            
            replies = comments_data.get('replies') or []
            if not replies:
                await self._print(f"   视频暂无评论")
                return
            replies_count = len(replies)
            
            await self._print(f"   获取到 {len(replies)} 条根评论 (总评论数: {total_comments})")
            
            # Jev 判断并发执行。
            candidates = replies[:COMMENT_CONFIG.get('max_replies_per_video', 5)]
            jev_limit = asyncio.Semaphore(JEV_FILTER_CONFIG.get('concurrency', 10))
            jev_results = await asyncio.gather(*[
                self._decide_comment_with_limit(title, cmt, jev_limit)
                for cmt in candidates
            ], return_exceptions=True)

            reply_context = None
            if any(
                not isinstance(result, Exception)
                and (
                    result['emergency_probability'] >= JEV_FILTER_CONFIG['emergency_threshold']
                    or (
                        result['needs_comfort_probability'] >= JEV_FILTER_CONFIG['needs_comfort_threshold']
                        and result['intensity'] >= JEV_FILTER_CONFIG['intensity_threshold']
                    )
                )
                for result in jev_results
            ):
                reply_context = await self._fetch_reply_context(bvid, title)

            # DeepSeek 生成并发执行，B站发送由发送锁和限流器保持串行。
            deepseek_limit = asyncio.Semaphore(
                DEEPSEEK_GENERATION_CONFIG.get('concurrency', 5)
            )
            tasks = []
            for cmt, jev_result in zip(candidates, jev_results):
                if isinstance(jev_result, Exception):
                    self.logger.error(
                        "Jev 判断失败 bvid=%s rpid=%s error_type=%s error=%r",
                        bvid, cmt.get('rpid'), type(jev_result).__name__, jev_result,
                    )
                    continue
                tasks.append(self._process_comment(
                    bvid, title, cmt, jev_result=jev_result,
                    deepseek_semaphore=deepseek_limit,
                    reply_context=reply_context
                ))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    if isinstance(result, BilibiliRiskError):
                        raise result
                    self.logger.error("处理评论任务失败 bvid=%s: %s", bvid, result)
                elif result:
                    processed += 1
            
            await self._print(f"   处理了 {processed} 条需要回复的评论")
            self._stats['videos_processed'] += 1
            
        except BilibiliRiskError:
            raise
        except Exception as e:
            self.logger.error(f"处理视频 {bvid} 失败: {e}")
            self._stats['errors'].append(f"处理视频 {bvid}: {e}")
            await self._print(f"   ⚠️ 处理视频失败: {type(e).__name__}: {e}")
            if replies_count:
                await self._print(f"   处理了 {processed} 条需要回复的评论（视频处理中断）")
    
    async def _decide_comment_with_limit(self, title: str, cmt: Dict, semaphore) -> dict:
        async with semaphore:
            return await self.jev_filter.decide_comment(
                title, (cmt.get('content') or {}).get('message', '')
            )

    async def _fetch_reply_context(self, bvid: str, title: str) -> Dict:
        """为同一视频准备一次共享上下文，避免并发任务重复抓取。"""
        video_summary = ""
        try:
            video_content = await self.video_extractor.extract_video_content(bvid)
            if video_content and video_content.get('summary'):
                video_summary = video_content['summary']
        except BilibiliRiskError:
            raise
        except Exception as e:
            self.logger.debug(f"获取视频内容失败: {e}")

        comments_context = ""
        try:
            if self.comment_context_fetcher:
                comments_context = await self.comment_context_fetcher.fetch_video_comments_context(
                    bvid=bvid,
                    max_comments=COMMENT_CONFIG.get('comments_context_count', 30),
                    include_replies=True
                )
        except BilibiliRiskError:
            raise
        except Exception as e:
            self.logger.debug(f"获取评论区上下文失败: {e}")

        return {'video_summary': video_summary, 'comments_context': comments_context}

    async def _process_comment(self, bvid: str, title: str, cmt: Dict, jev_result: Optional[Dict] = None,
                               deepseek_semaphore=None, reply_context: Optional[Dict] = None) -> bool:
        """处理单条评论，返回是否已回复（带评论区上下文）"""
        try:
            username = cmt['member']['uname']
            content = cmt['content']['message']
            comment_id = cmt['rpid']
            
            # 检查是否已回复（通过对话记录判断）
            existing_conv = await self.db.get_conversation_by_root(bvid, comment_id)
            retry_conv_id = None
            if existing_conv:
                existing_messages = existing_conv.get('messages') or []
                has_bot_reply = any(msg.get('role') == 'bot' for msg in existing_messages)
                if existing_conv.get('status') == 'new' and not has_bot_reply:
                    retry_conv_id = existing_conv['id']
                else:
                    await self.db.delete_comment_retry(bvid, comment_id)
                    return False

            if jev_result is None:
                jev_result = await self.jev_filter.decide_comment(title, content)
            needs_comfort = jev_result['needs_comfort_probability'] >= JEV_FILTER_CONFIG['needs_comfort_threshold']
            intensity = jev_result['intensity']
            is_emergency = jev_result['emergency_probability'] >= JEV_FILTER_CONFIG['emergency_threshold']
            self.logger.info(
                "Jev 评论判断 bvid=%s rpid=%s model=%s needs=%.3f intensity=%.2f emergency=%.3f emotion=%s",
                bvid, comment_id, jev_result['model'], jev_result['needs_comfort_probability'],
                intensity, jev_result['emergency_probability'], jev_result['emotion']
            )
            if not (needs_comfort and intensity >= JEV_FILTER_CONFIG['intensity_threshold']) and not is_emergency:
                await self.db.create_conversation(
                    bvid=bvid, root_comment_id=comment_id, user_mid=cmt['member']['mid'],
                    username=username, first_message=content, status='ignored'
                )
                await self.db.delete_comment_retry(bvid, comment_id)
                await self._print("      🚫 Jev 判断无需安慰，已忽略")
                return False
            
            # Jev 完成情感判断后，候选评论共享同一视频上下文。
            if reply_context is None:
                reply_context = await self._fetch_reply_context(bvid, title)
            video_summary = reply_context['video_summary']
            comments_context = reply_context['comments_context']
            
            sentiment_score = max(0.55, min(1.0, 0.55 + (intensity - 2.5) * 0.18))
            try:
                if deepseek_semaphore is None:
                    reply = await self._generate_initial_reply_with_protection(
                        title, video_summary, username, content, jev_result,
                        comments_context
                    )
                else:
                    async with deepseek_semaphore:
                        reply = await self._generate_initial_reply_with_protection(
                            title, video_summary, username, content, jev_result,
                            comments_context
                        )
            except Exception as e:
                self.logger.error(
                    "首次回复生成失败 bvid=%s rpid=%s error_type=%s error=%r",
                    bvid, comment_id, type(e).__name__, e,
                )
                await self.db.queue_comment_retry(bvid, title, cmt)
                return False
            if not reply:
                self.logger.warning("首次回复为空 bvid=%s rpid=%s", bvid, comment_id)
                await self.db.queue_comment_retry(bvid, title, cmt)
                return False
            from config.emoji_scenarios import get_emoji_for_emotion, get_emoji_for_sentiment
            emoji = (get_emoji_for_emotion(jev_result['emotion'], True) if is_emergency else
                     get_emoji_for_sentiment(sentiment_score, jev_result['emotion']))
            reply = reply.rstrip("。，！？ ") + emoji
            
            # 先创建对话记录，获取 conv_id
            conv_id = retry_conv_id or await self.db.create_conversation(
                bvid=bvid, root_comment_id=comment_id,
                user_mid=cmt['member']['mid'], username=username,
                first_message=content, status='new',
                next_check_at=datetime.now() + timedelta(hours=1)
            )
            await self.db.delete_comment_retry(bvid, comment_id)
            
            # 发送回复（使用有效的 conv_id）
            sent = await self._send_reply_with_protection(
                bvid=bvid,
                root_id=comment_id,
                parent_id=comment_id,
                content=reply,
                conv_id=conv_id,
                username=username,
                original_content=content
            )
            if not sent:
                # 保留候选评论，下一周期重试生成和发送。
                await self.db.queue_comment_retry(bvid, title, cmt)
                await self.db.update_conversation_status(
                    conv_id=conv_id,
                    status='new',
                    next_check_at=datetime.now() + timedelta(minutes=10)
                )
                return False
            
            # 检查是否为紧急情况，如果是则记录
            if is_emergency:
                await self._log_emergency(
                    bvid=bvid,
                    title=title,
                    username=username,
                    user_mid=cmt['member']['mid'],
                    content=content,
                    reply=reply,
                    emotion=jev_result['emotion'],
                    sentiment_score=sentiment_score
                )
            
            return True
            
        except BilibiliRiskError:
            raise
        except BilibiliNonRetryableError as e:
            self.logger.warning("跳过不可回复评论 bvid=%s: %s", bvid, e)
            return False
        except Exception as e:
            self.logger.error(f"处理评论失败: {e}")
            return False

    async def _generate_initial_reply_with_protection(
        self, title: str, video_summary: str, username: str, content: str,
        jev_result: Dict, comments_context: str
    ) -> Optional[str]:
        await deepseek_limiter.acquire()
        return await deepseek_breaker.call(
            deepseek_retry.execute, self.analyzer.generate_initial_reply,
            video_title=title, video_summary=video_summary,
            comment_username=username, comment_content=content,
            emotion=jev_result['emotion'],
            is_emergency=jev_result['emergency_probability'] >= JEV_FILTER_CONFIG['emergency_threshold'],
            comments_context=comments_context
        )
    
    async def _log_emergency(self, bvid: str, title: str, username: str, 
                            user_mid: int, content: str, reply: str,
                            emotion: str, sentiment_score: float):
        """记录紧急情况到文件"""
        try:
            from datetime import datetime
            
            log_content = f"""
================================================================================
🚨 紧急情况记录 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
================================================================================

📺 视频信息:
   标题: {title}
   BV号: {bvid}
   链接: https://www.bilibili.com/video/{bvid}

👤 用户信息:
   用户名: {username}
   UID: {user_mid}
   主页: https://space.bilibili.com/{user_mid}

💬 用户评论:
   {content}

🤖 我的回复:
   {reply}

📊 情感分析:
   情感类型: {emotion}
   情感分数: {sentiment_score:.2f} (越负越严重)

⚠️  建议操作:
   1. 点击用户主页查看其近期动态
   2. 关注该用户是否有后续回复
   3. 如有必要，考虑私信关心（但避免说教）
   4. 记录处理时间和方式

================================================================================

"""
            # 使用线程池执行文件写入（避免阻塞事件循环）
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, 
                self._write_emergency_log, 
                log_content
            )
            
            self.logger.warning(f"🚨 紧急情况已记录: {username} - {bvid}")
            
        except Exception as e:
            self.logger.error(f"记录紧急情况失败: {e}")
    
    def _write_emergency_log(self, content: str):
        """同步写入紧急情况日志"""
        try:
            EMERGENCY_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(EMERGENCY_LOG, 'a', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            self.logger.error(f"写入紧急情况日志失败: {e}")
    
    # ========== 统计 ==========
    
    async def _print_stats(self):
        """打印统计信息"""
        elapsed = time.time() - self._stats['start_time']
        
        await self._print(f"\n{'='*60}")
        await self._print("📊 本轮统计")
        await self._print(f"{'='*60}")
        await self._print(f"   处理视频: {self._stats['videos_processed']}")
        await self._print(f"   处理回复: {self._stats['replies_processed']}")
        await self._print(f"   发送回复: {self._stats['replies_sent']}")
        await self._print(f"   运行时间: {elapsed:.1f}秒")
        
        if self._stats['errors']:
            await self._print(f"   ⚠️  错误数: {len(self._stats['errors'])}")
        
        # 打印防护层状态
        await self._print(f"\n🛡️  防护层状态:")
        await self._print(f"   B站熔断器: {bilibili_breaker.state.value}")
        await self._print(f"   AI熔断器: {deepseek_breaker.state.value}")
        
        # 重置统计
        self._stats = {
            'videos_processed': 0,
            'replies_processed': 0,
            'replies_sent': 0,
            'api_calls': 0,
            'start_time': None,
            'errors': []
        }
