import asyncio
import unittest
import httpx
from modules.jev_filter import JevCommentFilter

class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
    async def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.responses.pop(0)

def response(answers):
    return httpx.Response(200, json={'model': 'jev-1.13.0', 'answers': answers},
                          request=httpx.Request('POST', JevCommentFilter.API_URL))

class JevFilterTests(unittest.TestCase):
    def test_comment_decision_uses_typed_questions(self):
        client = FakeClient([response({
            'needs_comfort': {'noul': .94}, 'emergency': {'noul': .01},
            'intensity': {'score': 3.4}, 'emotion': {'choice': '焦虑'}})])
        result = asyncio.run(JevCommentFilter('test-key', client).decide_comment('标题', '我睡不着'))
        self.assertEqual(result['needs_comfort_probability'], .94)
        self.assertEqual(result['intensity'], 3.4)
        payload = client.requests[0][1]['json']
        self.assertEqual(set(payload['questions']), {'needs_comfort', 'emergency', 'intensity', 'emotion'})
        self.assertEqual(payload['state']['comment'], '我睡不着')

    def test_continue_decision_uses_latest_reply_and_history(self):
        client = FakeClient([response({'next_action': {'choice': 'reply', 'confidence': .89, 'probabilities': {'reply': .94, 'close': .06}}})])
        result = asyncio.run(JevCommentFilter('test-key', client).decide_continue('我还有问题', [
            {'role': 'bot', 'content': '你好'}, {'role': 'user', 'content': '我还有问题'}]))
        self.assertTrue(result['should_reply'])
        self.assertEqual(client.requests[0][1]['json']['state']['latest_user_reply'], '我还有问题')

if __name__ == '__main__':
    unittest.main()
