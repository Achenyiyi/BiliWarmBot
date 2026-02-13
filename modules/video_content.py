"""
视频内容提取模块

负责从 Bilibili 视频获取多维度内容信息：
1. AI 视频总结 - 调用 B 站官方 AI 总结接口（5分钟以上视频）
2. 视频字幕 - 下载并解析 CC 字幕
3. 元数据 - 标题、描述、播放量等基础信息
4. 置顶评论 - 获取 UP 主自己发的置顶评论作为参考

内容获取优先级：
AI 总结 > 视频字幕 > 标题+描述

使用场景：
- 为 AI 分析评论提供视频上下文
- 理解视频主题和情感基调
- 获取 UP 主对视频的补充说明（置顶评论）
"""

import httpx
from typing import Optional, Dict
from bilibili_api import video, comment, Credential
from bilibili_api.comment import CommentResourceType


class VideoContentExtractor:
    """
    视频内容提取器
    
    封装视频信息获取的多种方式，根据视频特性自动选择最佳方案。
    对于长视频优先使用 AI 总结，短视频或无字幕视频降级使用其他方案。
    """
    
    def __init__(self, credential: Credential = None):
        self.credential = credential
    
    async def get_video_summary(self, bvid: str, cid: int, up_mid: int) -> Optional[str]:
        """
        获取 B 站官方 AI 视频总结
        
        B 站为 5 分钟以上的视频提供 AI 自动总结服务，
        包含视频概要、章节要点和关键词。
        
        Args:
            bvid: 视频 BV 号
            cid: 视频 CID（分 P 标识）
            up_mid: UP 主 MID（用于权限验证）
        
        Returns:
            结构化总结文本，包含概要、章节、关键词
            如果视频无总结或调用失败返回 None
        """
        try:
            v = video.Video(bvid=bvid, credential=self.credential)
            result = await v.get_ai_conclusion(cid=cid, up_mid=up_mid)
            
            if isinstance(result, dict) and result.get("code") == 0:
                data = result.get("data", {})
                model_result = data.get("model_result", {})
                
                summary = model_result.get("summary", "")
                
                # 追加章节大纲
                outline = model_result.get("outline", []) or model_result.get("chapters", [])
                if outline and summary:
                    summary += "\n\n【视频章节要点】\n"
                    for i, item in enumerate(outline[:10], 1):
                        title = item.get("title", "")
                        content = item.get("content", "")
                        if title:
                            summary += f"{i}. {title}"
                            if content:
                                summary += f"：{content[:50]}..."
                            summary += "\n"
                
                # 追加关键词
                keywords = model_result.get("keywords", [])
                if keywords and summary:
                    summary += f"\n【关键词】{', '.join(keywords[:10])}"
                
                if summary:
                    return summary
            
            return None
            
        except Exception:
            return None
    
    async def get_video_subtitle(self, bvid: str, cid: int = None) -> Optional[str]:
        """
        获取视频字幕文本
        
        优先获取中文（自动生成）字幕，如果没有则取第一个可用字幕。
        字幕内容用于理解视频讲述的具体内容。
        
        Args:
            bvid: 视频 BV 号
            cid: 视频 CID（可选，不传则自动获取）
        
        Returns:
            字幕纯文本（合并所有字幕片段）
            无字幕或获取失败返回 None
        """
        try:
            v = video.Video(bvid=bvid, credential=self.credential)
            
            # 获取视频信息（包含字幕信息）
            info = await v.get_info()
            if cid is None:
                cid = info.get("cid")
            
            subtitle_info = info.get("subtitle", {})
            
            if not subtitle_info or not subtitle_info.get("list"):
                return None
            
            subtitles = subtitle_info["list"]
            subtitle_url = None
            
            # 优先选择中文（自动生成）字幕
            for sub in subtitles:
                lan_doc = sub.get("lan_doc", "")
                if "中文" in lan_doc and "自动" in lan_doc:
                    subtitle_url = sub.get("subtitle_url")
                    break
            
            # 降级：使用第一个可用字幕
            if not subtitle_url and subtitles:
                subtitle_url = subtitles[0].get("subtitle_url")
            
            if not subtitle_url:
                return None
            
            # 规范化 URL
            if subtitle_url.startswith("//"):
                subtitle_url = "https:" + subtitle_url
            
            async with httpx.AsyncClient() as client:
                response = await client.get(subtitle_url)
                if response.status_code == 200:
                    subtitle_data = response.json()
                    
                    if "body" in subtitle_data:
                        text_parts = []
                        for item in subtitle_data["body"]:
                            content = item.get("content", "").strip()
                            if content:
                                text_parts.append(content)
                        
                        return " ".join(text_parts)
            
            return None
            
        except Exception:
            return None
    
    async def get_video_info(self, bvid: str) -> Dict:
        """
        获取视频基础信息
        
        Args:
            bvid: 视频 BV 号
        
        Returns:
            包含视频元数据的字典：
            - bvid/aid/cid: 视频标识
            - title/desc: 标题和描述
            - up_mid/up_name: UP 主信息
            - duration: 时长（秒）
            - view/danmaku/reply: 统计数据
        """
        try:
            v = video.Video(bvid=bvid, credential=self.credential)
            info = await v.get_info()
            
            return {
                "bvid": info.get("bvid"),
                "aid": info.get("aid"),
                "cid": info.get("cid"),
                "title": info.get("title"),
                "desc": info.get("desc"),
                "up_mid": info.get("owner", {}).get("mid"),
                "up_name": info.get("owner", {}).get("name"),
                "duration": info.get("duration"),
                "view": info.get("stat", {}).get("view"),
                "danmaku": info.get("stat", {}).get("danmaku"),
                "reply": info.get("stat", {}).get("reply")
            }
            
        except Exception:
            return {}
    
    async def get_top_comment(self, aid: int, up_mid: int) -> Optional[Dict]:
        """
        获取 UP 主自己发的置顶评论
        
        检查评论区多个可能的位置：
        1. top 字段（旧版 API）
        2. top_replies 字段（新版 API）
        3. replies 中标记 is_up_top 的评论
        
        严格的 UP 主校验：通过比对评论作者 MID 和 UP 主 MID，
        确保只返回 UP 主自己发的置顶评论。
        
        Args:
            aid: 视频 AV 号
            up_mid: UP 主 MID
        
        Returns:
            置顶评论字典（content/author/type）
            无置顶评论或不是 UP 主发的返回 None
        """
        try:
            result = await comment.get_comments(
                oid=aid,
                type_=CommentResourceType.VIDEO,
                page_index=1,
                credential=self.credential
            )
            
            if not isinstance(result, dict):
                return None
            
            # 检查点 1: top 字段（旧版 API）
            top_data = result.get('top')
            if top_data:
                if isinstance(top_data, dict):
                    content = top_data.get('content', {}).get('message', '')
                    author = top_data.get('member', {}).get('uname', '')
                    author_mid = top_data.get('member', {}).get('mid')
                    if content and str(author_mid) == str(up_mid):
                        return {"content": content, "author": author, "type": "top"}
                elif isinstance(top_data, list) and len(top_data) > 0:
                    first = top_data[0]
                    content = first.get('content', {}).get('message', '')
                    author = first.get('member', {}).get('uname', '')
                    author_mid = first.get('member', {}).get('mid')
                    if content and str(author_mid) == str(up_mid):
                        return {"content": content, "author": author, "type": "top"}
            
            # 检查点 2: top_replies 字段（新版 API）
            top_replies = result.get('top_replies', [])
            if top_replies:
                for top_cmt in top_replies:
                    content = top_cmt.get('content', {}).get('message', '')
                    author = top_cmt.get('member', {}).get('uname', '')
                    author_mid = top_cmt.get('member', {}).get('mid')
                    if content and str(author_mid) == str(up_mid):
                        return {"content": content, "author": author, "type": "top"}
            
            # 检查点 3: replies 中的 is_up_top 标记
            replies = result.get('replies', [])
            for cmt in replies:
                reply_control = cmt.get('reply_control', {})
                if reply_control.get('is_up_top'):
                    content = cmt.get('content', {}).get('message', '')
                    author = cmt.get('member', {}).get('uname', '')
                    author_mid = cmt.get('member', {}).get('mid')
                    if content and str(author_mid) == str(up_mid):
                        return {"content": content, "author": author, "type": "top"}
            
            return None
            
        except Exception:
            return None
    
    async def extract_video_content(self, bvid: str) -> Dict:
        """
        提取视频完整内容信息
        
        综合多种来源构建视频内容摘要，供 AI 分析评论时参考。
        
        获取策略：
        1. 5 分钟以上视频优先尝试 AI 总结
        2. 无 AI 总结时尝试获取字幕
        3. 无字幕时降级使用标题+描述
        4. 同时获取 UP 主置顶评论作为补充
        
        Args:
            bvid: 视频 BV 号
        
        Returns:
            视频内容字典：
            - bvid/title/up_mid: 基础信息
            - summary: 内容摘要（可能来自 AI/字幕/元数据）
            - source: 摘要来源标识（ai_summary/subtitle/meta）
            - has_subtitle: 是否有字幕
            - top_comment: UP 主置顶评论（如有）
        """
        info = await self.get_video_info(bvid)
        if not info:
            return {}
        
        bvid = info.get("bvid")
        cid = info.get("cid")
        aid = info.get("aid")
        up_mid = info.get("up_mid")
        title = info.get("title", "")
        duration = info.get("duration", 0)
        
        summary = None
        source = "meta"
        has_subtitle = False
        
        # 策略 1: AI 总结（5 分钟以上视频）
        if duration >= 300:
            summary = await self.get_video_summary(bvid, cid, up_mid)
            if summary:
                source = "ai_summary"
        
        # 策略 2: 视频字幕
        if not summary:
            subtitle_text = await self.get_video_subtitle(bvid, cid)
            if subtitle_text:
                summary = subtitle_text[:1500]
                if len(subtitle_text) > 1500:
                    summary += "..."
                has_subtitle = True
                source = "subtitle"
        
        # 策略 3: 标题+描述
        if not summary:
            desc = info.get('desc', '')
            # 只保留简介，标题会在prompt中单独提供，避免重复
            if desc:
                summary = f"【简介】{desc[:500]}"
            else:
                summary = "（该视频暂无简介）"
            source = "meta"
            source_display = "标题和简介"
        else:
            source_display = "B站AI总结" if source == "ai_summary" else "视频字幕"
        
        # 获取 UP 主置顶评论
        top_comment = None
        top_comment_display = ""
        if aid and up_mid:
            top_comment = await self.get_top_comment(aid, up_mid)
            if top_comment:
                top_comment_display = "+置顶"
        
        # 构建来源描述
        source_desc = f"{source_display}{top_comment_display}"
        
        return {
            "bvid": bvid,
            "title": title,
            "summary": summary,
            "up_mid": up_mid,
            "source": source,
            "source_desc": source_desc,
            "has_subtitle": has_subtitle,
            "top_comment": top_comment
        }
