import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime
from core.warm_bot import WarmBot

COMMENT = {'rpid': 123, 'member': {'mid': 456, 'uname': '测试用户'}, 'content': {'message': '普通评论'}}

class JevGateTests(unittest.TestCase):
    def make_bot(self, decision=None, error=None):
        bot = WarmBot.__new__(WarmBot)
        bot.db = Mock()
        bot.db.get_conversation_by_root = AsyncMock(return_value=None)
        bot.db.create_conversation = AsyncMock(return_value=1)
        bot.db.delete_comment_retry = AsyncMock()
        bot.db.queue_comment_retry = AsyncMock()
        bot.video_extractor = Mock()
        bot.video_extractor.extract_video_content = AsyncMock(return_value={'summary': '简介'})
        bot.comment_context_fetcher = None
        bot._print = AsyncMock()
        bot.logger = Mock()
        bot.jev_filter = Mock()
        bot.jev_filter.decide_comment = AsyncMock(side_effect=error, return_value=decision or {
            'model': 'jev-1.13.0', 'needs_comfort_probability': 0.01,
            'emergency_probability': 0.01, 'intensity': 0.1, 'emotion': '其他'})
        bot.jev_filter.decide_continue = AsyncMock(return_value={
            'model': 'jev-1.13.0', 'should_reply': True, 'confidence': 0.9})
        bot.analyzer = Mock()
        bot.analyzer.generate_initial_reply = AsyncMock(return_value='今晚先好好休息')
        bot._send_reply_with_protection = AsyncMock()
        bot._log_emergency = AsyncMock()
        return bot

    def test_irrelevant_comment_skips_deepseek(self):
        bot = self.make_bot()
        self.assertFalse(asyncio.run(bot._process_comment('BV123', '视频', COMMENT)))
        bot.analyzer.generate_initial_reply.assert_not_awaited()
        bot.video_extractor.extract_video_content.assert_not_awaited()
        self.assertEqual(bot.db.create_conversation.await_args.kwargs['status'], 'ignored')

    def test_relevant_comment_uses_deepseek_only_to_generate(self):
        decision = {'model': 'jev-1.13.0', 'needs_comfort_probability': 0.95,
                    'emergency_probability': 0.01, 'intensity': 3.4, 'emotion': '焦虑'}
        bot = self.make_bot(decision)
        with patch('core.warm_bot.deepseek_limiter.acquire', new_callable=AsyncMock), \
             patch('core.warm_bot.deepseek_breaker.call', new_callable=AsyncMock, return_value='今晚先好好休息'):
            self.assertTrue(asyncio.run(bot._process_comment('BV123', '视频', COMMENT)))
        bot._send_reply_with_protection.assert_awaited_once()
        self.assertEqual(bot.db.create_conversation.await_args.kwargs['status'], 'new')

    def test_deepseek_disconnect_queues_candidate(self):
        bot = self.make_bot({
            'model': 'jev-1.13.0', 'needs_comfort_probability': 0.95,
            'emergency_probability': 0.01, 'intensity': 3.4, 'emotion': '焦虑'})
        with patch('core.warm_bot.deepseek_limiter.acquire', new_callable=AsyncMock), \
             patch('core.warm_bot.deepseek_breaker.call', new_callable=AsyncMock,
                   side_effect=ConnectionError('Server disconnected')):
            self.assertFalse(asyncio.run(bot._process_comment('BV123', '视频', COMMENT)))
        bot.db.queue_comment_retry.assert_awaited_once_with('BV123', '视频', COMMENT)
        bot.db.create_conversation.assert_not_awaited()

    def test_comment_jev_result_can_be_precomputed(self):
        bot = self.make_bot({
            'model': 'jev-1.13.0', 'needs_comfort_probability': 0.01,
            'emergency_probability': 0.01, 'intensity': 0.1, 'emotion': '其他'})
        decision = {
            'model': 'jev-1.13.0', 'needs_comfort_probability': 0.01,
            'emergency_probability': 0.01, 'intensity': 0.1, 'emotion': '其他'}
        self.assertFalse(asyncio.run(bot._process_comment('BV123', '视频', COMMENT, decision)))
        bot.jev_filter.decide_comment.assert_not_awaited()

    def test_send_failure_keeps_conversation_retryable(self):
        decision = {'model': 'jev-1.13.0', 'needs_comfort_probability': 0.95,
                    'emergency_probability': 0.01, 'intensity': 3.4, 'emotion': '焦虑'}
        bot = self.make_bot(decision)
        bot.db.update_conversation_status = AsyncMock()
        bot.db.get_conversation_by_root.side_effect = [
            None,
            {'id': 1, 'status': 'new', 'messages': [{'role': 'user', 'content': '普通评论'}]},
        ]
        bot._send_reply_with_protection.side_effect = [False, True]
        with patch('core.warm_bot.deepseek_limiter.acquire', new_callable=AsyncMock), \
             patch('core.warm_bot.deepseek_breaker.call', new_callable=AsyncMock,
                   return_value='今晚先好好休息'):
            self.assertFalse(asyncio.run(bot._process_comment('BV123', '视频', COMMENT)))
            self.assertTrue(asyncio.run(bot._process_comment('BV123', '视频', COMMENT)))
        bot.db.queue_comment_retry.assert_awaited_once_with('BV123', '视频', COMMENT)
        bot.db.update_conversation_status.assert_awaited_once()
        self.assertEqual(bot.db.update_conversation_status.await_args.kwargs['status'], 'new')

    def test_continue_decision_does_not_call_deepseek(self):
        bot = self.make_bot()
        result = asyncio.run(bot._should_continue_with_protection('我还有问题', [], 2, 8))
        self.assertTrue(result['should_reply'])
        bot.analyzer.generate_initial_reply.assert_not_awaited()

    def test_close_decision_does_not_call_deepseek(self):
        bot = self.make_bot()
        bot.jev_filter.decide_continue.return_value = {
            'model': 'jev-1.13.0', 'should_reply': False, 'confidence': 0.9}
        result = asyncio.run(bot._should_continue_with_protection('谢谢', [], 2, 8))
        self.assertFalse(result['should_reply'])
        bot.analyzer.generate_initial_reply.assert_not_awaited()

    def test_manual_intervention_wins_over_same_batch_user_reply(self):
        bot = self.make_bot()
        bot.bot_uid = '999'
        bot.credential = Mock()
        bot.db.get_conversation_messages = AsyncMock(return_value=[
            {'role': 'user', 'content': '原始评论', 'rpid': '100'},
            {'role': 'bot', 'content': '机器人回复', 'rpid': '200'},
        ])
        bot.db.is_bot_comment = AsyncMock(side_effect=lambda rpid: str(rpid) == '200')
        bot.db.update_conversation_status = AsyncMock()
        bot.db.add_message = AsyncMock()
        bot._continue_conversation = AsyncMock()
        conv = {
            'id': 7, 'bvid': 'BV123', 'root_comment_id': 100,
            'user_mid': 456, 'status': 'replied',
            'last_reply_at': datetime.now(), 'created_at': datetime.now(),
            'updated_at': datetime.now(), 'check_count': 0,
        }
        replies = {
            'replies': [
                {'rpid': 300, 'parent': 200,
                 'member': {'mid': 456, 'uname': '用户'},
                 'content': {'message': '我还有问题'}},
                {'rpid': 400, 'parent': 100,
                 'member': {'mid': 999, 'uname': '人工账号'},
                 'content': {'message': '人工接管'}}
            ]
        }
        with patch('core.warm_bot.Comment') as comment_cls, patch('core.warm_bot.bvid2aid', return_value=1):
            comment_cls.return_value.get_sub_comments = AsyncMock(return_value=replies)
            asyncio.run(bot._check_conversation_updates(conv))
        bot._continue_conversation.assert_not_awaited()
        self.assertEqual(bot.logger.error.call_args_list, [])
        bot.db.update_conversation_status.assert_awaited_once_with(
            conv_id=7, status='paused', close_reason='manual_intervention')

if __name__ == '__main__':
    unittest.main()
