"""Jev 情感与续聊判断：只做判断，不生成回复。"""

import httpx
import asyncio


class JevCommentFilter:
    API_URL = "https://api.typesafe.ai/v1/systemone"
    MODEL = "jev-1.13.0"

    def __init__(self, api_key: str, client=None):
        self.api_key = api_key
        self._client = client
        self._owns_client = client is None
        self._client_lock = asyncio.Lock()

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
                    self._client = httpx.AsyncClient(timeout=15.0)
        response = await self._client.post(self.API_URL,
                                           headers={"Authorization": "Bearer " + self.api_key},
                                           json=payload)
        response.raise_for_status()
        return response.json()
