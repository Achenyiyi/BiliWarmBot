"""Jev 情感与续聊判断：只做判断，不生成回复。"""

import httpx
import asyncio
import random
import logging


class JevCommentFilter:
    API_URL = "https://api.typesafe.ai/v1/systemone"
    MODEL = "jev-1.13.0"
    MAX_RETRIES = 2
    RETRY_BASE_DELAY = 0.8

    def __init__(self, api_key: str, client=None):
        self.api_key = api_key
        self._client = client
        self._owns_client = client is None
        self._client_lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    async def close(self):
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def decide_comment(self, video_title: str, comment_content: str) -> dict:
        """一次请求取得初评所需判断；原始概率保留供审计。"""
        payload = {
            "model": self.MODEL,
            "state": {"video_title": video_title[:200], "comment": comment_content[:1500]},
            "questions": {
                "needs_comfort": {
                    "type": "noul",
                    "instructions": "Does the commenter personally describe current emotional suffering or a difficult life event and appear to need comfort? Mere jokes, emoji, advertisements, advice to others, or discussion of fictional people do not count. Judge only the comment, not the video title.",
                },
                "emergency": {
                    "type": "noul",
                    "instructions": "Does the commenter personally express a wish to die, self-harm, suicide intent or plan, or serious personal hopelessness? Include indirect wishes to die; exclude fiction, quotations, idioms and other people's situations.",
                },
                "intensity": {
                    "type": "score",
                    "instructions": "Rate the commenter's own expressed emotional distress, judging the comment itself rather than the video title.",
                    "criteria": [
                        "No personal distress; joke, emoji, advertisement, neutral comment or supporting another person",
                        "Minor personal frustration or disappointment",
                        "Mild personal sadness or tiredness",
                        "Clear personal distress, anxiety, grief, insomnia or significant difficulty",
                        "Severe personal suffering, despair or emotional breakdown",
                        "Personal self-harm or suicide risk",
                    ],
                },
                "emotion": {
                    "type": "choice",
                    "instructions": "Which emotion does the commenter personally express most strongly? Choose other if there is no clear personal emotion.",
                    "criteria": {
                        "悲伤": "Personal sadness or grief",
                        "焦虑": "Personal anxiety or worry",
                        "愤怒": "Personal anger",
                        "孤独": "Personal loneliness",
                        "绝望": "Personal hopelessness",
                        "无助": "Personal helplessness",
                        "其他": "No clear personal negative emotion or a different emotion",
                    },
                },
            },
        }
        body = await self._post(payload)
        answers = body["answers"]
        needs = self._probability(answers["needs_comfort"]["noul"])
        emergency = self._probability(answers["emergency"]["noul"])
        severity = float(answers["intensity"]["score"])
        emotion = answers["emotion"]["choice"]
        return {"model": body.get("model", self.MODEL), "needs_comfort_probability": needs,
                "emergency_probability": emergency, "intensity": severity,
                "emotion": emotion}

    async def decide_continue(self, user_reply: str, conversation_history: list) -> dict:
        """判断最新用户回复是否需要继续回应；轮数上限由调用代码控制。"""
        recent = [{"role": item.get("role"), "content": str(item.get("content", ""))[:500]}
                  for item in conversation_history[-5:]]
        payload = {
            "model": self.MODEL,
            "state": {"recent_messages": recent, "latest_user_reply": user_reply[:1000]},
            "questions": {
                "next_action": {
                    "type": "choice",
                    "instructions": "Should the assistant respond to the latest user reply? Judge the latest reply in context, not the whole conversation.",
                    "criteria": {
                        "reply": "The user asks a new question, shares a new personal feeling or situation, or meaningfully continues the exchange. A thanks followed by new substance also counts.",
                        "close": "The user explicitly asks to stop, says goodbye, only acknowledges or thanks the assistant, sends only an emoji or punctuation such as ?, says the assistant replied to the wrong person or is an AI bot, or gives no new substance.",
                    },
                },
            },
        }
        body = await self._post(payload)
        answer = body["answers"]["next_action"]
        return {"model": body.get("model", self.MODEL),
                "should_reply": answer["choice"] == "reply",
                "confidence": float(answer["confidence"]),
                "probabilities": answer["probabilities"]}

    @staticmethod
    def _probability(value):
        value = float(value)
        return value

    async def _post(self, payload: dict) -> dict:
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
                        http2=False,
                    )

        last_error = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = await self._client.post(
                    self.API_URL,
                    headers={"Authorization": "Bearer " + self.api_key},
                    json=payload,
                )
                # 参数/鉴权类 4xx 不重试；限流和服务端错误允许短暂退避。
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = exc
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code if exc.response is not None else None
                if status != 429 and (status is None or status < 500):
                    raise
            except (ValueError, TypeError):
                # 响应格式错误通常不是瞬时网络问题，直接交给上层记录。
                raise

            if attempt >= self.MAX_RETRIES:
                break
            delay = min(8.0, self.RETRY_BASE_DELAY * (2 ** attempt))
            delay *= random.uniform(0.8, 1.2)
            self.logger.warning(
                "Jev 请求失败，将重试 attempt=%d/%d error_type=%s error=%r",
                attempt + 1, self.MAX_RETRIES + 1, type(last_error).__name__, last_error,
            )
            await asyncio.sleep(delay)

        assert last_error is not None
        raise last_error
