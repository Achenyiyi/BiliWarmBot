"""
评论区上下文获取模块

功能：
1. 实时爬取视频评论区的全部内容
2. 格式化评论数据（用户名、时间戳、评论内容、回复关系）
3. 注入到AI系统提示词中，让AI了解评论区氛围

参考实现：基于 bilibili-api 的 comment 模块
"""

import asyncio
from datetime import datetime
from typing import List, Dict, Optional
from bilibili_api import comment, video
from bilibili_api.comment import CommentResourceType, OrderType
from bilibili_api.utils.network import Credential
from bilibili_api.utils.aid_bvid_transformer import bvid2aid


class CommentContextFetcher:
    """评论区上下文获取器"""
    
    def __init__(self, credential: Credential):
        self.credential = credential
    
    async def fetch_video_comments_context(
        self, 
        bvid: str, 
        max_comments: int = 50,
        include_replies: bool = True
    ) -> str:
        """
        获取视频评论区的格式化上下文
        
        Args:
            bvid: 视频BV号
            max_comments: 最大获取评论数（默认50条）
            include_replies: 是否包含楼中楼回复
            
        Returns:
            格式化后的评论区文本，例如：
            """
        try:
            # 获取视频信息
            v = video.Video(bvid=bvid, credential=self.credential)
            video_info = await v.get_info()
            title = video_info.get('title', '未知标题')
            
            # 获取评论
            comments_data = await self._fetch_comments(
                aid=v.get_aid(), 
                max_comments=max_comments,
                include_replies=include_replies
            )
            
            if not comments_data:
                return ""
            
            # 格式化为文本
            formatted_context = self._format_comments_to_text(
                title=title,
                comments=comments_data
            )
            
            return formatted_context
            
        except Exception as e:
            print(f"获取评论区上下文失败 BV{bvid}: {e}")
            return ""
    
    async def _fetch_comments(
        self, 
        aid: int, 
        max_comments: int = 50,
        include_replies: bool = True
    ) -> List[Dict]:
        """
        获取视频评论（包含子评论）
        
        参考：比例比例小虫虫_批量版.py 的实现逻辑
        """
        all_comments = []
        offset = ""
        page = 1
        max_pages = 10  # 限制最大页数
        
        try:
            while len(all_comments) < max_comments and page <= max_pages:
                # 获取评论
                result = await comment.get_comments_lazy(
                    oid=aid,
                    type_=CommentResourceType.VIDEO,
                    offset=offset,
                    order=OrderType.TIME,  # 按时间排序，最新的在前面
                    credential=self.credential
                )
                
                replies = result.get('replies', [])
                if not replies:
                    break
                
                # 处理每条评论
                for reply in replies:
                    if len(all_comments) >= max_comments:
                        break
                    
                    # 添加父评论
                    comment_data = self._parse_comment(reply)
                    if comment_data:
                        all_comments.append(comment_data)
                    
                    # 获取子评论（楼中楼）
                    if include_replies:
                        rcount = reply.get('rcount', 0)
                        if rcount > 0:
                            sub_comments = await self._fetch_sub_comments(
                                aid=aid,
                                parent_rpid=reply['rpid'],
                                parent_username=comment_data['username'] if comment_data else None
                            )
                            all_comments.extend(sub_comments)
                
                # 更新偏移量
                if 'cursor' in result and 'pagination_reply' in result['cursor']:
                    offset = result['cursor']['pagination_reply'].get('next_offset', '')
                else:
                    offset = ""
                
                if not offset:
                    break
                
                page += 1
                await asyncio.sleep(0.5)  # 避免请求过快
            
            return all_comments[:max_comments]
            
        except Exception as e:
            print(f"获取评论失败: {e}")
            return all_comments
    
    async def _fetch_sub_comments(
        self, 
        aid: int, 
        parent_rpid: int,
        parent_username: str = None
    ) -> List[Dict]:
        """获取子评论（楼中楼）"""
        sub_comments = []
        
        try:
            # 创建Comment对象
            cmt = comment.Comment(
                oid=aid,
                type_=CommentResourceType.VIDEO,
                rpid=parent_rpid,
                credential=self.credential
            )
            
            page_index = 1
            max_sub_pages = 3  # 限制子评论页数
            
            while page_index <= max_sub_pages:
                result = await cmt.get_sub_comments(
                    page_index=page_index, 
                    page_size=20
                )
                
                if not isinstance(result, dict):
                    break
                
                replies = result.get('replies', [])
                if not replies:
                    break
                
                for sub_reply in replies:
                    sub_comment_data = self._parse_sub_comment(
                        sub_reply, 
                        parent_rpid=parent_rpid,
                        parent_username=parent_username
                    )
                    if sub_comment_data:
                        sub_comments.append(sub_comment_data)
                
                if len(replies) < 20:
                    break
                
                page_index += 1
                await asyncio.sleep(0.3)
            
            return sub_comments
            
        except Exception as e:
            print(f"获取子评论失败 rpid={parent_rpid}: {e}")
            return sub_comments
    
    def _parse_comment(self, reply: Dict) -> Optional[Dict]:
        """解析父评论"""
        try:
            member = reply.get('member', {})
            content = reply.get('content', {})
            
            return {
                'rpid': reply.get('rpid'),
                'username': member.get('uname', '未知用户'),
                'ctime': reply.get('ctime', 0),
                'message': content.get('message', ''),
                'is_sub': False,
                'parent_username': None
            }
        except Exception as e:
            return None
    
    def _parse_sub_comment(
        self, 
        reply: Dict, 
        parent_rpid: int,
        parent_username: str = None
    ) -> Optional[Dict]:
        """解析子评论（楼中楼）"""
        try:
            member = reply.get('member', {})
            content = reply.get('content', {})
            
            # 检查是否是回复某个用户
            message = content.get('message', '')
            
            return {
                'rpid': reply.get('rpid'),
                'username': member.get('uname', '未知用户'),
                'ctime': reply.get('ctime', 0),
                'message': message,
                'is_sub': True,
                'parent_username': parent_username
            }
        except Exception as e:
            return None
    
    def _format_comments_to_text(self, title: str, comments: List[Dict]) -> str:
        """
        将评论数据格式化为文本
        
        格式示例：
        一只派大星喔 2025-11-15 10:57:52 三连[喜欢]
        柑橘味の小百合 2025-11-15 11:46:45 爱了爱了[小电视_太太喜欢]
        一只派大星喔 2025-11-15 12:57:30 回复 @柑橘味の小百合 :必须的，佬的每条视频必须三连
        """
        if not comments:
            return ""

        lines = []
        
        for cmt in comments:
            username = cmt['username']
            ctime = cmt['ctime']
            message = cmt['message']
            is_sub = cmt['is_sub']
            parent_username = cmt.get('parent_username')
            
            # 格式化时间
            time_str = datetime.fromtimestamp(ctime).strftime('%Y-%m-%d %H:%M:%S')
            
            # 格式化评论
            if is_sub and parent_username:
                # 子评论显示回复关系
                line = f"{username} {time_str} 回复 @{parent_username} :{message}"
            else:
                # 父评论
                line = f"{username} {time_str} {message}"
            
            lines.append(line)
        
        return "\n".join(lines)


# 便捷函数
async def get_comments_context(
    bvid: str,
    credential: Credential,
    max_comments: int = 50
) -> str:
    """
    便捷函数：获取视频评论区上下文
    
    使用示例：
        context = await get_comments_context("BV15eC5BBEA2", credential)
    """
    fetcher = CommentContextFetcher(credential)
    return await fetcher.fetch_video_comments_context(bvid, max_comments)
