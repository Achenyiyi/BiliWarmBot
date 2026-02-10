"""
数据库管理模块 - 柯南优化版

核心表：
1. tracked_videos - 追踪的视频
2. conversations - 对话记录（支持精细化状态管理）

状态机：
- new: 新建，尚未回复
- replied: 已回复，等待用户
- ignored: 非目标对话，忽略
- closed: 正常结束
"""

import sqlite3
import asyncio
import aiosqlite
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any
from contextlib import asynccontextmanager
from config import DATABASE_PATH


class DatabaseManager:
    """柯南优化版数据库管理器 - 支持精细化状态管理"""
    
    def __init__(self, db_path: Path = DATABASE_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database_sync()
    
    def _init_database_sync(self):
        """同步初始化数据库"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 视频追踪表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tracked_videos (
                    bvid TEXT PRIMARY KEY,
                    title TEXT,
                    total_comments INTEGER DEFAULT 0,
                    my_root_comment_id INTEGER,
                    last_check_at TIMESTAMP,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 对话记录表 - 支持精细化状态
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bvid TEXT NOT NULL,
                    root_comment_id INTEGER,
                    user_mid INTEGER,
                    username TEXT,
                    messages TEXT DEFAULT '[]',
                    status TEXT DEFAULT 'new',
                    last_reply_at TIMESTAMP,
                    next_check_at TIMESTAMP,
                    check_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 索引优化
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_bvid ON conversations(bvid)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_status ON conversations(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_next_check ON conversations(next_check_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_mid)")
            
            # 机器人发送的评论记录表 - 用于精确识别
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_comments (
                    comment_id INTEGER PRIMARY KEY,
                    bvid TEXT NOT NULL,
                    root_id INTEGER,
                    content TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bot_comments_bvid ON bot_comments(bvid)")
            
            conn.commit()
    
    @asynccontextmanager
    async def get_connection(self):
        """获取数据库连接"""
        conn = await aiosqlite.connect(self.db_path)
        try:
            conn.row_factory = aiosqlite.Row
            yield conn
        finally:
            await conn.close()
    
    # ========== 视频追踪相关 ==========
    
    async def track_video(self, bvid: str, title: str, total_comments: int = 0) -> bool:
        """追踪新视频"""
        async with self.get_connection() as conn:
            await conn.execute(
                """INSERT OR REPLACE INTO tracked_videos 
                   (bvid, title, total_comments, last_check_at, status)
                   VALUES (?, ?, ?, ?, 'active')""",
                (bvid, title, total_comments, datetime.now())
            )
            await conn.commit()
            return True
    
    async def get_tracked_video(self, bvid: str) -> Optional[Dict]:
        """获取追踪的视频信息"""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM tracked_videos WHERE bvid = ?",
                (bvid,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
    
    async def get_active_videos(self) -> List[Dict]:
        """获取所有活跃的视频"""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM tracked_videos WHERE status = 'active'"
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def update_video_comment_count(self, bvid: str, count: int):
        """更新视频评论数"""
        async with self.get_connection() as conn:
            await conn.execute(
                "UPDATE tracked_videos SET total_comments = ? WHERE bvid = ?",
                (count, bvid)
            )
            await conn.commit()
    
    # ========== 对话相关（柯南优化版） ==========
    
    async def create_conversation(self, bvid: str, root_comment_id: int,
                                   user_mid: int, username: str,
                                   first_message: str, status: str = 'new',
                                   next_check_at: datetime = None) -> int:
        """创建新对话（支持指定初始状态）"""
        messages = [{
            "role": "user",
            "content": first_message,
            "time": datetime.now().isoformat(),
            "rpid": root_comment_id  # 记录根评论ID，用于后续去重
        }]
        
        # 如果没有指定 next_check_at，根据状态自动设置
        if next_check_at is None and status == 'replied':
            next_check_at = datetime.now() + timedelta(hours=1)
        
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO conversations 
                   (bvid, root_comment_id, user_mid, username, messages, 
                    status, last_reply_at, next_check_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (bvid, root_comment_id, user_mid, username, json.dumps(messages, ensure_ascii=False),
                 status, datetime.now(), next_check_at, datetime.now())
            )
            await conn.commit()
            return cursor.lastrowid
    
    async def get_conversation(self, conv_id: int) -> Optional[Dict]:
        """获取对话"""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (conv_id,)
            )
            row = await cursor.fetchone()
            if row:
                data = dict(row)
                data['messages'] = json.loads(data['messages'])
                return data
            return None
    
    async def get_conversation_by_root(self, bvid: str, root_comment_id: int) -> Optional[Dict]:
        """通过根评论ID获取对话"""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM conversations WHERE bvid = ? AND root_comment_id = ?",
                (bvid, root_comment_id)
            )
            row = await cursor.fetchone()
            if row:
                data = dict(row)
                data['messages'] = json.loads(data['messages'])
                return data
            return None
    
    async def get_conversations_by_status(self, status: str) -> List[Dict]:
        """获取指定状态的对话"""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM conversations WHERE status = ?",
                (status,)
            )
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                data = dict(row)
                data['messages'] = json.loads(data['messages'])
                result.append(data)
            return result
    
    async def get_replied_conversations_to_check(self) -> List[Dict]:
        """获取需要检查的已回复对话（next_check_at到期）"""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """SELECT * FROM conversations 
                   WHERE status = 'replied' AND next_check_at <= ?""",
                (datetime.now(),)
            )
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                data = dict(row)
                data['messages'] = json.loads(data['messages'])
                result.append(data)
            return result
    
    async def add_message(self, conv_id: int, role: str, content: str, rpid: int = None):
        """添加消息到对话"""
        conv = await self.get_conversation(conv_id)
        if not conv:
            return False
        
        messages = conv['messages']
        message_data = {
            "role": role,
            "content": content,
            "time": datetime.now().isoformat()
        }
        if rpid:
            message_data["rpid"] = rpid
        messages.append(message_data)
        
        async with self.get_connection() as conn:
            await conn.execute(
                """UPDATE conversations 
                   SET messages = ?, updated_at = ? 
                   WHERE id = ?""",
                (json.dumps(messages, ensure_ascii=False), datetime.now(), conv_id)
            )
            await conn.commit()
            return True
    
    async def get_conversation_messages(self, conv_id: int) -> List[Dict]:
        """获取对话的所有消息"""
        conv = await self.get_conversation(conv_id)
        if not conv:
            return []
        return conv.get('messages', [])
    
    async def update_conversation_status(self, conv_id: int, status: str, 
                                         next_check_at: datetime = None,
                                         check_count: int = None,
                                         close_reason: str = None):
        """更新对话状态"""
        async with self.get_connection() as conn:
            # 构建动态更新语句
            fields = ["status = ?", "updated_at = ?"]
            values = [status, datetime.now()]
            
            if next_check_at is not None:
                fields.append("next_check_at = ?")
                values.append(next_check_at)
            
            if check_count is not None:
                fields.append("check_count = ?")
                values.append(check_count)
            
            if close_reason is not None:
                fields.append("close_reason = ?")
                values.append(close_reason)
            
            values.append(conv_id)
            
            sql = f"""UPDATE conversations 
                      SET {', '.join(fields)} 
                      WHERE id = ?"""
            
            await conn.execute(sql, values)
            await conn.commit()
            return True
    
    async def update_conversation_after_reply(self, conv_id: int, reply_content: str):
        """回复后更新对话状态（状态变为 replied）"""
        conv = await self.get_conversation(conv_id)
        if not conv:
            return False
        
        messages = conv['messages']
        messages.append({
            "role": "bot",
            "content": reply_content,
            "time": datetime.now().isoformat()
        })
        
        check_count = conv['check_count'] + 1
        # 检查次数超过5次，关闭对话
        status = 'closed' if check_count >= 5 else 'replied'
        
        async with self.get_connection() as conn:
            await conn.execute(
                """UPDATE conversations 
                   SET messages = ?, 
                       status = ?,
                       last_reply_at = ?,
                       next_check_at = ?,
                       check_count = ?,
                       updated_at = ?
                   WHERE id = ?""",
                (json.dumps(messages, ensure_ascii=False), status, datetime.now(),
                 datetime.now() + timedelta(hours=2), check_count, 
                 datetime.now(), conv_id)
            )
            await conn.commit()
            return True
    
    async def increment_check_count(self, conv_id: int) -> bool:
        """增加检查次数，超过5次则关闭"""
        conv = await self.get_conversation(conv_id)
        if not conv:
            return False
        
        check_count = conv['check_count'] + 1
        status = 'closed' if check_count >= 5 else conv['status']
        
        async with self.get_connection() as conn:
            await conn.execute(
                """UPDATE conversations 
                   SET check_count = ?, status = ?, next_check_at = ?, updated_at = ?
                   WHERE id = ?""",
                (check_count, status, 
                 datetime.now() + timedelta(hours=2),
                 datetime.now(), conv_id)
            )
            await conn.commit()
            return True
    
    async def close_conversation(self, conv_id: int):
        """关闭对话"""
        async with self.get_connection() as conn:
            await conn.execute(
                """UPDATE conversations 
                   SET status = 'closed', updated_at = ? 
                   WHERE id = ?""",
                (datetime.now(), conv_id)
            )
            await conn.commit()
    
    async def ignore_conversation(self, conv_id: int):
        """标记对话为忽略（非目标对话）"""
        async with self.get_connection() as conn:
            await conn.execute(
                """UPDATE conversations 
                   SET status = 'ignored', updated_at = ? 
                   WHERE id = ?""",
                (datetime.now(), conv_id)
            )
            await conn.commit()
    
    # ========== 机器人评论记录 ==========
    
    async def record_bot_comment(self, comment_id: int, bvid: str, root_id: int, content: str):
        """记录机器人发送的评论"""
        async with self.get_connection() as conn:
            await conn.execute(
                """INSERT OR REPLACE INTO bot_comments 
                   (comment_id, bvid, root_id, content, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (comment_id, bvid, root_id, content, datetime.now())
            )
            await conn.commit()
    
    async def is_bot_comment(self, comment_id: int) -> bool:
        """检查某条评论是否是机器人发送的"""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT 1 FROM bot_comments WHERE comment_id = ?",
                (comment_id,)
            )
            return await cursor.fetchone() is not None
    
    async def get_bot_comment_by_root(self, bvid: str, root_id: int) -> Optional[Dict]:
        """获取机器人在某视频某评论下的回复"""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """SELECT * FROM bot_comments 
                   WHERE bvid = ? AND root_id = ?""",
                (bvid, root_id)
            )
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    # ========== 统计相关 ==========
    
    async def get_conversation_stats(self) -> Dict:
        """获取对话统计"""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """SELECT status, COUNT(*) as count 
                   FROM conversations 
                   GROUP BY status"""
            )
            rows = await cursor.fetchall()
            return {row['status']: row['count'] for row in rows}
    
    async def close(self):
        """关闭数据库连接池"""
        # aiosqlite使用上下文管理器，这里不需要额外操作
        # 但为了API一致性，保留此方法
        pass
