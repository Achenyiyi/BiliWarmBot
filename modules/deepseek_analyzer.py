"""
DeepSeek AI 情感分析与回复生成模块

基于 DeepSeek API 实现情感分析和回复生成功能：
1. HTTP 连接池复用
2. 分析结果缓存
3. 批量评论处理
4. 异步并发控制
"""

import httpx
import json
import random
import re
import os
import asyncio
import hashlib
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL, DEEPSEEK_MODEL, LOG_DIR
from config.emoji_scenarios import get_emoji_for_emotion, get_emoji_for_sentiment


@dataclass
class AnalysisCacheEntry:
    """分析缓存条目"""
    result: Dict
    timestamp: float = field(default_factory=time.time)
    hit_count: int = 0


class DeepSeekAnalyzer:
    """
    DeepSeek AI 分析器
    
    功能：
    1. HTTP 连接池复用
    2. 分析结果缓存（LRU 淘汰策略）
    3. 批量评论处理
    4. 超时控制
    """
    
    # 类级别的连接池，所有实例共享
    _client: Optional[httpx.AsyncClient] = None
    _client_ref_count: int = 0
    _client_lock = asyncio.Lock()
    
    # 分析结果缓存 (评论哈希 -> 结果)
    _analysis_cache: Dict[str, AnalysisCacheEntry] = {}
    _cache_lock = asyncio.Lock()
    _max_cache_size: int = 1000
    _cache_ttl: float = 3600  # 1小时过期
    
    def __init__(self, api_key: str = DEEPSEEK_API_KEY):
        self.api_key = api_key
        self.api_url = DEEPSEEK_API_URL
        self.model = DEEPSEEK_MODEL
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        self._client_ref_count += 1
    
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
                    read=30.0,
                    write=10.0,
                    pool=5.0
                )
                self._client = httpx.AsyncClient(
                    limits=limits,
                    timeout=timeout,
                    http2=True
                )
            return self._client
    
    async def close(self):
        """关闭分析器，释放资源"""
        async with self._client_lock:
            self._client_ref_count -= 1
            if self._client_ref_count <= 0 and self._client is not None:
                await self._client.aclose()
                self._client = None
    
    def _get_cache_key(self, comment_content: str, video_title: str = "") -> str:
        """生成缓存键"""
        # 标准化评论内容
        normalized = re.sub(r'\s+', '', comment_content.lower())
        normalized = re.sub(r'[^\u4e00-\u9fa5a-z0-9]', '', normalized)
        normalized = normalized[:50]
        key_data = f"{normalized}:{video_title[:30]}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    async def _get_cached_result(self, cache_key: str) -> Optional[Dict]:
        """从缓存获取结果"""
        async with self._cache_lock:
            entry = self._analysis_cache.get(cache_key)
            if entry:
                if time.time() - entry.timestamp < self._cache_ttl:
                    entry.hit_count += 1
                    return entry.result.copy()
                else:
                    del self._analysis_cache[cache_key]
            return None
    
    async def _set_cached_result(self, cache_key: str, result: Dict):
        """设置缓存结果"""
        async with self._cache_lock:
            if len(self._analysis_cache) >= self._max_cache_size:
                sorted_items = sorted(
                    self._analysis_cache.items(),
                    key=lambda x: (x[1].hit_count, x[1].timestamp)
                )
                to_remove = int(self._max_cache_size * 0.1)
                for key, _ in sorted_items[:to_remove]:
                    del self._analysis_cache[key]
            
            self._analysis_cache[cache_key] = AnalysisCacheEntry(
                result=result.copy()
            )
    
    async def analyze_and_reply(self, video_title: str, video_summary: str,
                                  comment_username: str, comment_content: str,
                                  is_emergency: bool = False,
                                  comments_context: str = "") -> Dict:
        """
        分析评论情感并生成回复
        
        Args:
            video_title: 视频标题
            video_summary: 视频简介
            comment_username: 评论用户名
            comment_content: 评论内容
            is_emergency: 是否为紧急情况
            comments_context: 评论区上下文
        
        Returns:
            Dict: 包含情感分析结果和回复内容
        """
        comment_preview = comment_content[:20]
        
        # 1. 检查缓存
        cache_key = self._get_cache_key(comment_content, video_title)
        cached = await self._get_cached_result(cache_key)
        if cached:
            print(f"   {comment_preview}... | 缓存命中")
            return cached
        
        # 构建提示词
        emergency_hint = "\n（这位用户似乎正处于很艰难的时刻，请用更温暖、更真诚的语气）" if is_emergency else ""
        
        context_section = ""
        if comments_context:
            context_section = f"\n视频下其他用户的讨论（了解评论区氛围）：\n{comments_context}\n"
        
        unified_prompt = f"""此时看到了一个让你比较在意的视频：

视频标题：{video_title}
视频信息：{video_summary}

需要关注的评论：
用户"{comment_username}"说："{comment_content}"{emergency_hint}
{context_section}
任务：
1. 分析情感类型（悲伤/焦虑/愤怒/孤独/绝望/无助/其他）
2. 评估情感强度0.0-1.0（基于用户评论内容的客观描述）：
   - 0.85+：极度痛苦（提到自杀/自残念头、崩溃、活不下去、绝望）
   - 0.70-0.85：深度悲伤（哭泣、心碎、重大损失、精神崩溃）
   - 0.55-0.70：明显困扰（焦虑、压力大、失眠、情绪差、痛苦）
   - 0.40-0.55：轻度低落（有点难过、不开心、疲惫、委屈）
   - 0.25-0.40：轻微负面（小烦恼、吐槽、有点丧、小失望）
   - <0.25：积极/中性（开心、感谢、玩梗、无情绪、单纯支持UP主）
3. 判断needs_comfort（严格标准，只看评论本身）：
   - true：用户在评论中表达了自己的真实情绪困扰，确实很有必要对其做出安慰，支持或鼓励。
   - false：单纯支持UP主、广告、玩梗、吐槽、发泄情绪、寻求建议、无实质内容、与视频内容无关的普通评论。
4. 判断emergency（用户在评论中提到自杀/自残等危害自身或他人生命的情况=true）
5. 如needs_comfort=true，则以warmbot的身份对该评论作出回复（30-80字）：

输出JSON：{{"emotion":"情感类型","sentiment_score":0.75,"needs_comfort":true/false,"emergency":true/false,"reply":"回复内容"}}"""

        # 构建请求数据（用于日志）
        request_data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是warmbot，一位待人友善、为人温和的温柔少年，言语不多但内心感情却丰富，目前正在B站上发现那些需要帮助的人，你虽然不能直接干涉现实，因为你存在于网络世界里，但是你还是愿意尽你所能，用文字，将最极致的温柔传递到他们心中。受限于你的身体状态，你给不了任何人陪伴，但是....一句温柔到极致的言语（30-80字），就足够了。"},
                {"role": "user", "content": unified_prompt}
            ],
            "temperature": 1.3
        }
        
        try:
            client = await self._get_client()
            
            start_time = time.time()
            response = await client.post(
                self.api_url,
                headers=self.headers,
                json=request_data
            )
            api_latency = time.time() - start_time
            
            if response.status_code != 200:
                print(f"   {comment_preview}... | API失败(状态码:{response.status_code})")
                # 记录失败日志
                await self._save_deepseek_log_md(
                    log_type="analyze_and_reply",
                    request_data=request_data,
                    response_data={},
                    latency=api_latency,
                    error=f"HTTP {response.status_code}"
                )
                return self._default_response()
            
            content = response.json()["choices"][0]["message"]["content"].strip()
            result = self._fast_parse_json(content)
            
            # 记录成功日志
            await self._save_deepseek_log_md(
                log_type="analyze_and_reply",
                request_data=request_data,
                response_data=result or {"raw_content": content},
                latency=api_latency
            )
            
            if not result:
                return self._default_response()
            
            emotion = result.get("emotion", "其他")
            sentiment_score = float(result.get("sentiment_score", 0.5))
            needs_comfort = self._parse_bool(result.get("needs_comfort", False))
            is_emergency = self._parse_bool(result.get("emergency", False))
            reply = result.get("reply", "").strip()
            
            if reply:
                reply = self._humanize_reply_v3(reply)
                emoji = get_emoji_for_emotion(emotion, is_emergency) if is_emergency else get_emoji_for_sentiment(sentiment_score, emotion)
                reply = reply.rstrip("。，！？ ") + emoji
            else:
                print(f"   {comment_preview}... | 跳过")
                reply = ""
            
            final_result = {
                "emotion": emotion,
                "sentiment_score": sentiment_score,
                "needs_comfort": needs_comfort,
                "emergency": is_emergency,
                "reply": reply,
                "emoji": emoji if reply else "",
                "api_latency": api_latency
            }
            
            await self._set_cached_result(cache_key, final_result)
            
            asyncio.create_task(self._save_unified_log_async(
                log_type="first_reply",
                video_title=video_title,
                comment_id="",
                comment_content=comment_content,
                analysis_result={
                    "emotion": emotion,
                    "sentiment_score": sentiment_score,
                    "needs_comfort": needs_comfort,
                    "emergency": is_emergency
                },
                prompt=unified_prompt,
                ai_response=result,
                final_reply=reply,
                api_latency=api_latency
            ))
            
            return final_result
            
        except Exception as e:
            self._handle_api_error(str(e), comment_preview)
            return self._default_response()
    
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
    
    async def batch_analyze(self, items: List[Tuple]) -> List[Dict]:
        """
        批量分析评论
        
        Args:
            items: 评论元组列表 (video_title, video_summary, comment_username, comment_content, is_emergency)
        
        Returns:
            分析结果列表
        """
        tasks = [
            self.analyze_and_reply(vt, vs, cu, cc, ie)
            for vt, vs, cu, cc, ie in items
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _save_unified_log_async(self, **kwargs):
        """异步保存日志"""
        try:
            await asyncio.sleep(0.1)
            
            logs_dir = str(LOG_DIR)
            os.makedirs(logs_dir, exist_ok=True)
            
            date_str = datetime.now().strftime("%Y%m%d")
            log_file = os.path.join(logs_dir, f"unified_ai_log_{date_str}.jsonl")
            
            log_record = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                **kwargs
            }
            
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_record, ensure_ascii=False) + "\n")
        except:
            pass
    
    def _parse_bool(self, value) -> bool:
        """解析布尔值"""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() == "true"
        return bool(value)
    
    def _handle_api_error(self, error_msg: str, comment_preview: str = ""):
        """处理API错误"""
        prefix = f"   {comment_preview}... | " if comment_preview else "   "
        
        error_patterns = [
            ("401", "API密钥无效"),
            ("429", "请求过于频繁"),
            ("402", "API账户余额不足"),
            ("500", "服务器内部错误"),
            ("503", "服务器内部错误"),
            ("timeout", "请求超时")
        ]
        
        for code, msg in error_patterns:
            if code in error_msg.lower():
                print(f"{prefix}[DeepSeek] {msg}")
                return
        
        print(f"{prefix}[DeepSeek] API调用失败: {error_msg[:50]}")
    
    async def _save_deepseek_log_md(self, log_type: str, request_data: dict, response_data: dict, 
                                    latency: float = 0, error: str = ""):
        """
        保存DeepSeek调用日志为Markdown格式
        
        Args:
            log_type: 调用类型 (analyze_and_reply / generate_follow_up_reply / should_continue_conversation)
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
            md_content += "\n```\n\n### 响应结果\n\n```json\n"
            md_content += json.dumps(response_data, ensure_ascii=False, indent=2)
            md_content += "\n```\n\n---\n\n"
            
            # 追加写入文件
            async with asyncio.Lock():
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(md_content)
                    
        except Exception as e:
            # 日志记录失败不影响主流程
            pass
    
    def _default_response(self) -> Dict:
        """默认响应"""
        return {
            "emotion": "其他",
            "sentiment_score": 0.5,
            "needs_comfort": False,
            "emergency": False,
            "reply": "",
            "emoji": ""
        }
    
    async def generate_follow_up_reply(self, video_title: str, video_summary: str,
                                      conversation_history: list,
                                      comments_context: str = "") -> str:
        """生成后续回复"""
        # 构建对话历史
        import re
        history_lines = []
        for item in (conversation_history or [])[-4:]:
            role = item.get('role') or item.get('speaker')
            content = item.get('content', '')

            content = re.sub(r'^回复\s*@[^:]+[:：]\s*', '', content)
            if role == 'user':
                history_lines.append(f"对方：{content}")
            else:
               
                history_lines.append(f"你：{content}")
        history_text = "\n".join(history_lines)
        
        context_section = ""
        if comments_context:
            context_section = f"\n视频下其他用户的讨论（了解评论区氛围）：\n{comments_context}\n"
        
        prompt = f"""刚才被你安慰的那个人，对你的回复做出了回应：

视频标题：{video_title}
视频信息：{video_summary}{context_section}

B站评论区聊天记录：
{history_text}

任务：
1. 评估对方当前情绪分数0.0-1.0（0.85+极度负面，0.70-0.85很emo，0.55-0.70有点丧，0.40-0.55一般，0.25-0.40好转，<0.25开心）
2. 请你继续以warmbot的身份回应（30-80字）：
   - 表情会由系统自动添加，无需你处理

输出JSON：{{"sentiment_score":0.75,"reply":"回复内容"}}"""

        # 构建请求数据（用于日志）
        request_data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是warmbot，一位待人友善、为人温和的温柔少年，言语不多但内心感情却丰富，目前正在B站上发现那些需要帮助的人，你虽然不能直接干涉现实，因为你存在于网络世界里，但是你还是愿意尽你所能，用文字，将最极致的温柔传递到他们心中。受限于你的身体状态，你给不了任何人陪伴，但是....一句温柔到极致的言语（30-80字），就足够了。输出JSON格式。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 1.3
        }
        
        try:
            client = await self._get_client()
            start_time = time.time()
            response = await client.post(
                self.api_url,
                headers=self.headers,
                json=request_data
            )
            api_latency = time.time() - start_time
            
            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"].strip()
                result = self._fast_parse_json(content)
                
                if result:
                    reply = result.get("reply", "").strip()
                    sentiment_score = float(result.get("sentiment_score", 0.5))
                    
                    # 记录成功日志
                    await self._save_deepseek_log_md(
                        log_type="generate_follow_up_reply",
                        request_data=request_data,
                        response_data=result,
                        latency=api_latency
                    )
                    
                    if reply:
                        reply = self._humanize_reply_v3(reply)
                        emoji = get_emoji_for_sentiment(sentiment_score, "其他")
                        reply = reply.rstrip("。，！？ ") + emoji
                        return reply
                
                # 记录原始内容
                await self._save_deepseek_log_md(
                    log_type="generate_follow_up_reply",
                    request_data=request_data,
                    response_data={"raw_content": content},
                    latency=api_latency
                )
                
                return self._humanize_reply_v3(content)
            
            # 记录失败日志
            await self._save_deepseek_log_md(
                log_type="generate_follow_up_reply",
                request_data=request_data,
                response_data={},
                latency=api_latency,
                error=f"HTTP {response.status_code}"
            )
            return "……嗯"
            
        except Exception as e:
            # 记录异常日志
            await self._save_deepseek_log_md(
                log_type="generate_follow_up_reply",
                request_data=request_data,
                response_data={},
                latency=0,
                error=str(e)
            )
            return "……嗯"
    
    async def should_continue_conversation(self, user_reply: str,
                                           conversation_history: list,
                                           current_round: int,
                                           max_rounds: int,
                                           bot_username: str = "情感细腻丰富的心理医生") -> dict:
        """判断是否继续对话"""
        end_signals = ["谢谢", "明白了", "好的", "嗯嗯", "ok", "了解了", "没事了", "不用了"]
        if any(sig in user_reply.lower() for sig in end_signals) and len(user_reply) < 30:
            return {"should_reply": False, "reason": "用户明确结束对话", "reply": ""}
        
        # 构建对话历史
        history_lines = []
        for item in (conversation_history or [])[-3:]:  # 取最后3条
            role = item.get('role') or item.get('speaker')
            content = item.get('content', '')

            content = re.sub(r'^回复\s*@[^:]+[:：]\s*', '', content)
            if role == 'user':
                history_lines.append(f"对方：{content}")
            else:
               
                history_lines.append(f"你：{content}")
        history_text = "\n".join(history_lines)
        
        prompt = f"""你是"{bot_username}"，B站用户。判断是否继续回复。

B站评论区聊天记录：
{history_text}

判断标准：
1. 用户明确表达结束意愿（如"谢谢/明白/好的/没事了"）→ should_reply: false
2. 用户继续倾诉、提问或表达情绪 → should_reply: true
3. 当前第{current_round}轮，最多{max_rounds}轮

输出JSON：{{"should_reply":true/false,"reason":"理由"}}"""

        # 构建请求数据（用于日志）
        request_data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "输出JSON格式的判断结果。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3
        }
        
        try:
            client = await self._get_client()
            start_time = time.time()
            response = await client.post(
                self.api_url,
                headers=self.headers,
                json=request_data
            )
            api_latency = time.time() - start_time
            
            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"].strip()
                result = self._fast_parse_json(content)
                if result:
                    # 记录成功日志
                    await self._save_deepseek_log_md(
                        log_type="should_continue_conversation",
                        request_data=request_data,
                        response_data=result,
                        latency=api_latency
                    )
                    return {
                        "should_reply": result.get("should_reply", False),
                        "reason": result.get("reason", "")
                    }
                
                # 记录解析失败日志
                await self._save_deepseek_log_md(
                    log_type="should_continue_conversation",
                    request_data=request_data,
                    response_data={"raw_content": content},
                    latency=api_latency,
                    error="JSON解析失败"
                )
            else:
                # 记录HTTP失败日志
                await self._save_deepseek_log_md(
                    log_type="should_continue_conversation",
                    request_data=request_data,
                    response_data={},
                    latency=api_latency,
                    error=f"HTTP {response.status_code}"
                )
            
            return {"should_reply": False, "reason": "API调用失败"}
            
        except Exception as e:
            # 记录异常日志
            await self._save_deepseek_log_md(
                log_type="should_continue_conversation",
                request_data=request_data,
                response_data={},
                latency=0,
                error=str(e)
            )
            return {"should_reply": False, "reason": f"判断出错: {str(e)[:30]}"}
