"""
Bilibili 评论互动模块

功能：
1. 视频搜索 - 基于关键词和场景优先级搜索
2. 评论获取 - 获取视频根评论
3. 评论发送 - 发送回复
4. 紧急检测 - 识别高风险关键词
"""

import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from bilibili_api import search, comment, video
from bilibili_api.search import SearchObjectType, OrderVideo
from bilibili_api.comment import CommentResourceType, OrderType
from bilibili_api.utils.network import Credential

logger = logging.getLogger(__name__)


class CommentList(list):
    """评论列表，携带总评论数"""
    
    def __init__(self, comments: List[Dict], total_count: int = 0):
        super().__init__(comments)
        self._total_count = total_count
    
    @property
    def total_count(self) -> int:
        return self._total_count


class CommentInteractor:
    """Bilibili 评论交互器"""
    
    def __init__(self, credential: Credential, db_manager=None):
        self.credential = credential
        self.db = db_manager
        self.seen_bvids = set()
    
    async def search_negative_videos(self, keywords: Dict[str, List[str]], 
                                     max_results: int = 20,
                                     time_range_days: int = 7,
                                     scene_priority: Dict = None) -> List[Dict]:
        """搜索负面情感视频"""
        videos = []
        scene_videos_count = {}
        
        if not scene_priority:
            return await self._search_random(keywords, max_results, time_range_days)
        
        print(f"\n搜索: {max_results}个视频 | {time_range_days}天内\n")
        
        # 第一轮：确保每个场景都有最小视频数
        for priority_name, scenes in [
            ("high", scene_priority.get("high", [])),
            ("medium", scene_priority.get("medium", [])),
            ("low", scene_priority.get("low", []))
        ]:
            for scene in scenes:
                if scene not in keywords or len(videos) >= max_results:
                    break
                
                current_count = scene_videos_count.get(scene, 0)
                if current_count >= 3:
                    continue
                
                needed = min(3 - current_count, max_results - len(videos))
                if needed <= 0:
                    continue
                
                scene_keywords = keywords[scene][:20]
                scene_videos = await self._search_scene_simple(
                    scene, scene_keywords, time_range_days, needed
                )
                videos.extend(scene_videos)
                scene_videos_count[scene] = scene_videos_count.get(scene, 0) + len(scene_videos)
        
        # 第二轮：继续填充直到达到总数
        if len(videos) < max_results:
            for priority_name, scenes in [
                ("high", scene_priority.get("high", [])),
                ("medium", scene_priority.get("medium", [])),
                ("low", scene_priority.get("low", []))
            ]:
                if len(videos) >= max_results:
                    break
                
                for scene in scenes:
                    if scene not in keywords or len(videos) >= max_results:
                        break
                    
                    current_count = scene_videos_count.get(scene, 0)
                    if current_count >= 20:
                        continue
                    
                    needed = min(20 - current_count, max_results - len(videos))
                    if needed <= 0:
                        continue
                    
                    scene_keywords = keywords[scene][:20]
                    scene_videos = await self._search_scene_simple(
                        scene, scene_keywords, time_range_days, needed
                    )
                    videos.extend(scene_videos)
                    scene_videos_count[scene] = scene_videos_count.get(scene, 0) + len(scene_videos)
        
        # 打印统计
        if scene_videos_count:
            results = [f"{s}:{c}" for s, c in sorted(scene_videos_count.items(), key=lambda x: -x[1]) if c > 0]
            print(f"\n结果: {', '.join(results)} | 共{len(videos)}个\n")
        
        return videos
    
    async def _search_scene_simple(self, scene_name: str, keywords: List[str], 
                                    time_range_days: int, max_needed: int) -> List[Dict]:
        """搜索单个场景"""
        videos = []
        
        for keyword in keywords:
            if len(videos) >= max_needed:
                break
            
            try:
                keyword_videos = await self._search_keyword(
                    keyword, scene_name, time_range_days, max_needed - len(videos)
                )
                videos.extend(keyword_videos)
                await asyncio.sleep(0.3)
            except Exception as e:
                error_msg = str(e)
                if "412" in error_msg:
                    logger.warning(f"搜索请求被风控(412): {error_msg[:50]}")
                elif "-401" in error_msg:
                    logger.error(f"登录失效(-401): {error_msg[:50]}")
                continue
        
        return videos
    
    async def _search_keyword(self, keyword: str, category: str, 
                              time_range_days: int, max_needed: int) -> List[Dict]:
        """搜索单个关键词，实时去重，已处理的视频会继续搜索下一页"""
        videos = []
        page = 1
        max_pages = 10  # 最多搜索10页，防止无限循环
        
        while len(videos) < max_needed and page <= max_pages:
            try:
                result = await search.search_by_type(
                    keyword=keyword,
                    search_type=SearchObjectType.VIDEO,
                    order_type=OrderVideo.PUBDATE,
                    time_start=(datetime.now() - timedelta(days=time_range_days)).strftime('%Y-%m-%d'),
                    time_end=datetime.now().strftime('%Y-%m-%d'),
                    page=page,
                    page_size=20
                )
                
                page_videos = self._parse_search_result(result)
                
                if not page_videos:
                    break
                
                new_videos = []
                for v in page_videos:
                    bvid = v.get("bvid")
                    if not bvid:
                        continue
                    
                    # 检查是否已在此轮搜索中见过
                    if bvid in self.seen_bvids:
                        continue
                    
                    # 检查数据库是否已处理过
                    if self.db and await self.db.get_tracked_video(bvid):
                        self.seen_bvids.add(bvid)  # 标记为已见，避免重复检查
                        continue
                    
                    self.seen_bvids.add(bvid)
                    new_videos.append({
                        "bvid": bvid,
                        "title": v.get("title", "").replace('<em class="keyword">', "").replace('</em>', ""),
                        "category": category,
                        "keyword": keyword,
                        "pubdate": datetime.fromtimestamp(v.get("pubdate", 0)),
                        "description": v.get("description", ""),
                        "up_name": v.get("author", ""),
                        "up_mid": v.get("mid", 0)
                    })
                    
                    if len(videos) + len(new_videos) >= max_needed:
                        break
                
                videos.extend(new_videos)
                
                # 即使当前页没有新视频，也继续搜索下一页（可能后面的视频是新的）
                page += 1
                await asyncio.sleep(0.3)
                
            except Exception:
                break
        
        return videos
    
    async def _search_random(self, keywords: Dict[str, List[str]], 
                            max_results: int, time_range_days: int) -> List[Dict]:
        """随机搜索（无优先级配置时的降级策略）"""
        videos = []
        
        all_keywords = []
        for category, words in keywords.items():
            for word in words:
                all_keywords.append((category, word))
        random.shuffle(all_keywords)
        
        for category, keyword in all_keywords:
            if len(videos) >= max_results:
                break
            
            try:
                keyword_videos = await self._search_keyword(
                    keyword, category, time_range_days, max_results - len(videos)
                )
                videos.extend(keyword_videos)
                await asyncio.sleep(0.3)
            except Exception:
                continue
        
        return videos
    
    def _parse_search_result(self, result) -> List[Dict]:
        """解析 Bilibili 搜索结果"""
        if not isinstance(result, dict):
            return []
        
        if "result" in result:
            result_data = result["result"]
            if isinstance(result_data, list):
                return result_data
            elif isinstance(result_data, dict):
                if "data" in result_data:
                    return result_data["data"]
                elif "videos" in result_data:
                    return result_data["videos"]
        
        return []
    
    async def get_video_comments(self, bvid: str) -> CommentList:
        """获取视频全部根评论"""
        comments = []
        total_count = 0
        
        try:
            v = video.Video(bvid=bvid, credential=self.credential)
            info = await v.get_info()
            aid = info.get("aid")
            
            if not aid:
                return CommentList([], 0)
            
            page = 1
            while True:
                result = await comment.get_comments(
                    oid=aid,
                    type_=CommentResourceType.VIDEO,
                    order=OrderType.TIME,
                    page_index=page,
                    credential=self.credential
                )
                
                if isinstance(result, dict):
                    if page == 1:
                        total_count = result.get("data", {}).get("cursor", {}).get("all_count", 0)
                        if not total_count:
                            total_count = result.get("page", {}).get("count", 0)
                    
                    replies = result.get("replies", [])
                    if not replies:
                        break
                    
                    for reply in replies:
                        comments.append({
                            "rpid": reply.get("rpid"),
                            "oid": aid,
                            "mid": reply.get("mid"),
                            "uname": reply.get("member", {}).get("uname", ""),
                            "content": reply.get("content", {}).get("message", ""),
                            "ctime": reply.get("ctime"),
                            "like": reply.get("like", 0)
                        })
                    
                    if len(replies) < 20:
                        break
                else:
                    break
                
                page += 1
                await asyncio.sleep(random.uniform(1.0, 2.0))
            
            return CommentList(comments, total_count)
            
        except Exception as e:
            error_msg = str(e)
            if "412" in error_msg:
                logger.warning(f"获取评论被风控(412): {error_msg[:50]}")
            elif "-401" in error_msg:
                logger.error(f"登录失效: {error_msg[:50]}")
            return CommentList([], 0)
    
    async def send_reply(self, oid: int, content: str, root: int = None,
                         parent: int = None, reply_to_uname: str = None,
                         reply_to_content: str = None) -> Optional[int]:
        """发送评论回复"""
        try:
            # 简化回复格式：只保留"回复 @用户名"，不引用原话
            if reply_to_uname:
                full_content = f"回复 @{reply_to_uname} :\n{content}"
            else:
                full_content = content
            
            result = await comment.send_comment(
                text=full_content,
                oid=oid,
                type_=CommentResourceType.VIDEO,
                root=root,
                parent=parent,
                credential=self.credential
            )
            
            if isinstance(result, dict):
                code = result.get("code")
                if code == 0 or "success_toast" in result:
                    rpid = result.get("data", {}).get("rpid") if result.get("data") else result.get("rpid")
                    if rpid:
                        return rpid
                    else:
                        logger.warning(f"评论发送成功但未返回rpid: {result}")
                        return None
                else:
                    error_msg = result.get('message', '未知错误')
                    error_code = result.get('code', '未知错误码')
                    logger.error(f"发送评论失败: 错误码 {error_code}, {error_msg[:50]}")
                    
                    if error_code == 12051:
                        logger.warning("该评论已存在相同内容")
                    
                    return None
            else:
                logger.error(f"发送评论返回格式异常: {type(result)}")
                return None
            
        except Exception as e:
            error_msg = str(e)
            if "412" in error_msg:
                logger.warning(f"发送评论被风控(412): {error_msg[:50]}")
            elif "-401" in error_msg:
                logger.error(f"登录失效: {error_msg[:50]}")
            elif "-403" in error_msg:
                logger.warning(f"发送评论过于频繁: {error_msg[:50]}")
            return None
    
    def check_emergency(self, content: str, emergency_keywords: List[str]) -> bool:
        """检测紧急关键词"""
        content_lower = content.lower()
        for keyword in emergency_keywords:
            if keyword in content_lower:
                return True
        return False
