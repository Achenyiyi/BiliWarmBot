import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from modules.comment_interaction import CommentInteractor


class CommentSearchTests(unittest.TestCase):
    def test_search_skips_videos_with_zero_review_count(self):
        db = Mock()
        db.get_tracked_video = AsyncMock(return_value=None)
        interactor = CommentInteractor(Mock(), db)
        result = {
            'result': [
                {'bvid': 'BV-no-comments', 'title': '无评论', 'video_review': 0, 'pubdate': 1},
                {'bvid': 'BV-has-comments', 'title': '有评论', 'video_review': 3, 'pubdate': 1},
            ]
        }
        initial = {'replies': [{'rpid': 1}], 'page': {'count': 3}}
        with patch('modules.comment_interaction.search.search_by_type',
                   new_callable=AsyncMock, return_value=result), \
             patch.object(interactor, '_fetch_initial_comments', new_callable=AsyncMock,
                          return_value=initial) as probe:
            videos = asyncio.run(interactor._search_keyword('测试', '场景', 1, 1))

        self.assertEqual([video['bvid'] for video in videos], ['BV-has-comments'])
        probe.assert_awaited_once_with('BV-has-comments')

    def test_probe_failure_is_not_cached_as_no_comments(self):
        db = Mock()
        db.get_tracked_video = AsyncMock(return_value=None)
        interactor = CommentInteractor(Mock(), db)
        result = {'result': [
            {'bvid': 'BV-failed', 'title': '探测失败', 'pubdate': 1}
        ]}
        interactor._parse_search_result = Mock(return_value=result['result'])
        interactor._fetch_initial_comments = AsyncMock(return_value=None)
        with patch('modules.comment_interaction.search.search_by_type',
                   new_callable=AsyncMock, return_value=result):
            self.assertEqual(
                asyncio.run(interactor._search_keyword('测试', '场景', 1, 1)), []
            )
        self.assertNotIn('BV-failed', interactor._no_comment_bvids)

    def test_malformed_review_count_falls_back_to_probe(self):
        db = Mock()
        db.get_tracked_video = AsyncMock(return_value=None)
        interactor = CommentInteractor(Mock(), db)
        result = {'result': [
            {'bvid': 'BV-formatted', 'title': '格式化评论数', 'video_review': '1.2万', 'pubdate': 1}
        ]}
        with patch('modules.comment_interaction.search.search_by_type',
                   new_callable=AsyncMock, return_value=result), \
             patch.object(interactor, '_fetch_initial_comments', new_callable=AsyncMock,
                          return_value={'replies': [{'rpid': 1}]}) as probe:
            videos = asyncio.run(interactor._search_keyword('测试', '场景', 1, 1))
        self.assertEqual(videos[0]['bvid'], 'BV-formatted')
        probe.assert_awaited_once_with('BV-formatted')


if __name__ == '__main__':
    unittest.main()
