"""
DeepSeek 回复生成模块

基于 DeepSeek API 生成首次回复和后续回复，判断由 Jev 完成。
"""

import httpx
import json
import random
import re
import os
import asyncio
import time
from datetime import datetime
from typing import Dict, List, Optional
from config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL, DEEPSEEK_MODEL, LOG_DIR, DEEPSEEK_TEMPERATURE, DEEPSEEK_MAX_TOKENS


DEEPSEEK_PERSONA = (
    "你是一位18岁三不（不主动、不拒绝、不负责）少女，情场高手，对人：暧昧，只撩不追，"
    "假性温柔，边界感模糊，情感供养者，言语轻柔简洁，内心细腻。目前正在B站刷视频。"
    "你的表达应如同日常说话般：口语化；如同在微信，抖音上聊天一样：自然、随意；"
    "不是机械呆板的书面语，而是贴近日常表达习惯。虽然你存在于网络世界里，不能干涉现实世界。"
    "但你总是那么温柔，尽管只能使用文字，也要将最极致的温柔传递到他们有些伤痕的心中。"
    "受限于你的身体情况，你给不了任何人现实中的陪伴，但是...一条温柔到极致且不给对方任何压力的消息，"
    "目前来说，就足够了。"
)


class DeepSeekAnalyzer:
    """
    DeepSeek 回复生成器
    
    功能：HTTP 连接池复用、回复生成及超时控制。
    """
    
    # 类级别的连接池，所有实例共享
    _client: Optional[httpx.AsyncClient] = None
    _client_ref_count: int = 0
    _client_lock = asyncio.Lock()
    
    def __init__(self, api_key: str = DEEPSEEK_API_KEY):
        self.api_key = api_key
        self.api_url = DEEPSEEK_API_URL
        self.model = DEEPSEEK_MODEL
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        self._client_ref_count += 1
    
    def _is_reasoning_model(self) -> bool:
        """判断当前是否为推理模型（reasoner）"""
        return "reasoner" in self.model.lower()
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        async with self._client_lock:
            if self._client is None or self._client.is_closed:
                limits = httpx.Limits(
                    max_keepalive_connections=20,
                    max_connections=50,
                    keepalive_expiry=30.0
                )
                timeout = httpx.Timeout(
                    connect=5.0,
                    read=60.0,
                    write=10.0,
                    pool=5.0
                )
                self._client = httpx.AsyncClient(
                    limits=limits,
                    timeout=timeout,
                    # DeepSeek 偶发 Server disconnected 多发生在 HTTP/2 连接复用链路。
                    # 使用 HTTP/1.1 仍保持连接池，但避免该链路级断连。
                    http2=False
                )
            return self._client
    
    async def close(self):
        """关闭分析器，释放资源"""
        async with self._client_lock:
            self._client_ref_count -= 1
            if self._client_ref_count <= 0 and self._client is not None:
                await self._client.aclose()
                self._client = None

    async def generate_initial_reply(self, video_title: str, video_summary: str,
                                     comment_username: str, comment_content: str,
                                     emotion: str, is_emergency: bool = False,
                                     comments_context: str = "") -> str:
        """只生成首次回复文字；是否回复、情绪和危机均由 Jev 决定。"""
        prompt = (
            f"视频标题：{video_title}\n视频信息：{video_summary[:1500]}\n"
            f"评论者：{comment_username}\n评论：{comment_content}\n"
            f"评论区背景：{comments_context[:1500]}\n"
            f"已判定情绪：{emotion}；危机：{'是' if is_emergency else '否'}。\n"
            "请只写一条针对这位评论者的自然、具体、简短的安慰回复，30到80个汉字。"
            "不要重新判断是否需要回复，不要提及模型或评分。"
        )
        request_data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": f"{DEEPSEEK_PERSONA}只输出回复文字，不输出JSON。避免诊断、保证结果或编造亲身经历。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": DEEPSEEK_TEMPERATURE,
        }
        if not self._is_reasoning_model() and DEEPSEEK_MAX_TOKENS is not None:
            request_data["max_tokens"] = DEEPSEEK_MAX_TOKENS
        client = await self._get_client()
        response = await client.post(self.api_url, headers=self.headers, json=request_data)
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"].strip()
        return self._humanize_reply_v3(text)
    
    def _fast_parse_json(self, content: str) -> Optional[Dict]:
        """解析 JSON 内容"""
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content)
            if match:
                try:
                    return json.loads(match.group())
                except:
                    pass
        return None
    
    def _humanize_reply_v3(self, reply: str) -> str:
        """处理回复内容，移除正式词汇和表情"""
        if not reply:
            return ""
        
        formal_words = {
            "您好": "", "你好": "", "希望": "", "祝愿": "",
            "一定": "", "必须": "", "应该": "", "请": "",
            "加油": "", "一切都会好起来的": ""
        }
        for word, repl in formal_words.items():
            reply = reply.replace(word, repl)
        
        reply = re.sub(r'[❤️🫂😢🌟😭💖✨💪🙏🤗😔😊🔥💔💕🥺👉👈]', '', reply)
        
        reply = re.sub(r'[【\[][\u4e00-\u9fa5]+[】\]]', '', reply)
        
        lines = [' '.join(line.split()) for line in reply.split('\n') if line.strip()]
        reply = '\n'.join(lines)
        
        if reply and reply[-1].isalpha() and random.random() < 0.3:
            reply += random.choice(["啊", "哦", "呀", "呢", "啦", "哇"])
        
        return reply.strip()
    
    async def _save_deepseek_log_md(self, log_type: str, request_data: dict, response_data: dict, 
                                    latency: float = 0, error: str = ""):
        """
        保存DeepSeek调用日志为Markdown格式
        
        Args:
            log_type: 调用类型
            request_data: 请求数据
            response_data: 响应数据
            latency: API调用耗时(秒)
            error: 错误信息(如果有)
        """
        try:
            logs_dir = str(LOG_DIR)
            os.makedirs(logs_dir, exist_ok=True)
            
            date_str = datetime.now().strftime("%Y%m%d")
            log_file = os.path.join(logs_dir, f"deepseek_api_log_{date_str}.md")
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 构建MD内容
            md_content = f"""## API调用记录 - {timestamp}

### 基本信息
- **调用类型**: `{log_type}`
- **API URL**: {self.api_url}
- **模型**: {self.model}
- **调用耗时**: {latency:.3f}s
"""
            
            if error:
                md_content += f"- **状态**: ❌ 失败\n- **错误信息**: {error}\n"
            else:
                md_content += f"- **状态**: ✅ 成功\n"
            
            md_content += "\n### 请求参数\n\n#### System Prompt\n```\n"
            system_prompt = request_data.get('messages', [{}])[0].get('content', '')
            md_content += system_prompt[:500] + ("..." if len(system_prompt) > 500 else "")
            md_content += "\n```\n\n#### User Prompt\n```\n"
            user_prompt = request_data.get('messages', [{}, {}])[1].get('content', '')
            md_content += user_prompt
            md_content += "\n```\n\n#### 完整请求\n```json\n"
            md_content += json.dumps(request_data, ensure_ascii=False, indent=2)
            md_content += "\n### 响应结果\n\n"
            
            # 如果有思维链（推理模型），单独展示
            reasoning_content = response_data.get("reasoning_content", "")
            if reasoning_content:
                md_content += "#### 思维链 (Reasoning)\n```\n"
                md_content += reasoning_content
                md_content += "\n```\n\n"
                # 从response_data中移除，避免在JSON中重复显示
                response_data_for_json = {k: v for k, v in response_data.items() if k != "reasoning_content"}
            else:
                response_data_for_json = response_data
            
            md_content += "#### 最终结果\n```json\n"
            md_content += json.dumps(response_data_for_json, ensure_ascii=False, indent=2)
            md_content += "\n```\n\n---\n\n"
            
            # 追加写入文件
            async with asyncio.Lock():
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(md_content)
                    
        except Exception as e:
            # 日志记录失败不影响主流程
            pass
    
    async def generate_follow_up_reply(self, video_title: str, video_summary: str,
                                      conversation_history: list,
                                      comments_context: str = "") -> str:
        """生成后续回复（使用累积messages格式保持对话连贯性）"""
        import re
        
        # 构建累积式messages数组
        messages = [
            {"role": "system", "content": "只输出回复文字。"}
        ]
        
        # 添加对话历史（最多保留最近6轮，防止超出上下文限制）
        for item in (conversation_history or [])[-6:]:
            role = item.get('role') or item.get('speaker')
            content = item.get('content', '')
            
            # 清理回复中的@用户名前缀
            content = re.sub(r'^回复\s*@[^:]+[:：]\s*', '', content)
            
            if role == 'user':
                messages.append({"role": "user", "content": content})
            else:
                messages.append({"role": "assistant", "content": content})
        
        # 添加当前任务提示（作为最后一条user消息）
        # 获取最后一条用户消息（真正需要回复的内容）
        last_user_message = ""
        for item in reversed(conversation_history or []):
            if item.get('role') == 'user' or item.get('speaker') == 'user':
                last_user_message = item.get('content', '')
                # 清理@前缀
                last_user_message = re.sub(r'^回复\s*@[^:]+[:：]\s*', '', last_user_message)
                break
        
        context_section = ""
        if comments_context:
            context_section = f"\n顺便看看评论区，了解下他们在说什么：\n{comments_context}\n"
        
        task_prompt = f"""视频标题：{video_title}
视频信息：{video_summary}{context_section}

对方刚刚回复你说："{last_user_message}"

请只针对这条具体回复写一条自然、简短的回应。不要做情感分析、判断是否继续或输出JSON。"""
        
        messages.append({"role": "user", "content": task_prompt})
        
        # 构建请求数据
        request_data = {
            "model": self.model,
            "messages": messages,
            "temperature": DEEPSEEK_TEMPERATURE
        }
        
        # 只有非推理模型且配置了 max_tokens 时才设置
        if not self._is_reasoning_model() and DEEPSEEK_MAX_TOKENS is not None:
            request_data["max_tokens"] = DEEPSEEK_MAX_TOKENS
        
        client = await self._get_client()
        response = await client.post(self.api_url, headers=self.headers, json=request_data)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        return self._humanize_reply_v3(content)
