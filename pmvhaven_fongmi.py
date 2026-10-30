
# -*- coding: utf-8 -*-
"""
PMVHaven - FongMi Python Spider

功能：
1. 所有视频、热门视频、最受欢迎
2. 真实 API 分页
3. 关键词搜索
4. 点击作者查看作者视频
5. 点击标签查看标签视频
6. 横版 16:9 封面
7. 视频标题、时长、播放量
8. 直接 MP4 播放
9. 不显示推荐分类和相关推荐

依赖：Python 标准库 + FongMi base.spider
"""

import json
import base64
import re
import urllib.parse as U
import urllib.request as R
import urllib.error

from base.spider import Spider as BaseSpider


HOST = "https://pmvhaven.com"

UA = (
    "Mozilla/5.0 (Linux; Android 13) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Mobile Safari/537.36"
)

HEADERS = {
    "User-Agent": UA,
    "Referer": HOST + "/",
    "Origin": HOST,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

CATEGORIES = {
    "all": {
        "sort": "-releaseDate",
        "limit": 32,
    },
    "trending": {
        "sort": "-views",
        "trending": "true",
        "limit": 32,
    },
    "popular": {
        "sort": "-likes",
        "limit": 32,
    },
}


def safe_page(value):
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def encode_data(data):
    """将视频元数据编码进 vod_id，避免跨页面丢失播放地址。"""
    raw = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":")
    ).encode("utf-8")

    return base64.urlsafe_b64encode(raw).decode(
        "ascii"
    ).rstrip("=")


def decode_data(value):
    try:
        value = str(value)
        padding = "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(
            (value + padding).encode("ascii")
        )
        result = json.loads(raw.decode("utf-8"))
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def format_views(value):
    try:
        value = int(value)
    except (ValueError, TypeError):
        return "0"

    if value >= 10000:
        return "{:.1f}万".format(value / 10000)

    return str(value)


def clean_name(value):
    return re.sub(r"[$#\r\n]", " ", str(value or "")).strip()


class Spider(BaseSpider):

    def getName(self):
        return "PMVHaven"

    def init(self, extend=""):
        self.video_cache = {}
        self.last_error = ""

    def destroy(self):
        pass

    def isVideoFormat(self, url):
        return bool(
            re.search(
                r"\.(?:mp4|m3u8)(?:\?|$)",
                str(url),
                re.I
            )
        )

    def manualVideoCheck(self):
        return False

    def _request_json(self, url):
        req = R.Request(url, headers=HEADERS)

        try:
            with R.urlopen(req, timeout=20) as response:
                body = response.read().decode(
                    "utf-8", "replace"
                )

            data = json.loads(body)

            if not isinstance(data, dict):
                self.last_error = "接口返回格式错误"
                return None

            if data.get("success") is False:
                self.last_error = str(
                    data.get("message", "接口请求失败")
                )
                return None

            self.last_error = ""
            return data

        except Exception as e:
            self.last_error = str(e)
            return None

    def _video_info(self, video):
        """从真实 JSON 中提取视频元数据。"""
        if not isinstance(video, dict):
            return None

        vid = str(video.get("_id") or "").strip()
        title = str(video.get("title") or "").strip()

        if not vid or not title:
            return None

        sizes = video.get("thumbnailSizes") or {}
        lg = sizes.get("lg") or {}

        pic = (
            video.get("thumbnailUrl")
            or lg.get("url")
            or ""
        )

        if not pic:
            pic = (
                "https://pmvhavencloud."
                "s3.eu-west-par.io.cloud.ovh.net/"
                "thumbnails/{}/thumb_lg.webp"
            ).format(vid)

        return {
            "_id": vid,
            "title": title,
            "videoUrl": video.get("videoUrl") or "",
            "thumbnailUrl": pic,
            "uploaderId": str(
                video.get("uploaderId") or ""
            ),
            "uploaderUsername": (
                video.get("uploaderUsername")
                or video.get("uploader")
                or ""
            ),
            "tags": video.get("tags") or [],
            "starsTags": video.get("starsTags") or [],
            "duration": video.get("duration") or "",
            "views": video.get("views") or 0,
            "likes": video.get("likes") or 0,
            "releaseDate": video.get("releaseDate") or "",
            "width": video.get("width") or 0,
            "height": video.get("height") or 0,
        }

    def _to_card(self, video):
        info = self._video_info(video)

        if not info:
            return None

        vid = info["_id"]

        if not hasattr(self, "video_cache"):
            self.video_cache = {}

        self.video_cache[vid] = info

        # 使用编码后的元数据，避免进入详情页后
        # 必须再次请求视频接口。
        vod_id = "pmv:" + encode_data(info)

        duration = info["duration"]
        views = format_views(info["views"])

        remarks = "{} | {}播放".format(
            duration, views
        ) if duration else "{}播放".format(views)

        return {
            "vod_id": vod_id,
            "vod_name": info["title"],
            "vod_pic": info["thumbnailUrl"],
            "vod_remarks": remarks,
            "style": {
                "type": "rect",
                "ratio": 1.78
            }
        }

    def _parse_list(self, data, page, limit):
        """统一处理六种列表接口。"""
        empty = {
            "list": [],
            "page": page,
            "pagecount": page,
            "limit": limit,
            "total": 0,
        }

        if not isinstance(data, dict):
            return empty

        videos = data.get("videos")

        # 兼容部分接口将列表包在 data 内的情况。
        if not isinstance(videos, list):
            nested = data.get("data")
            if isinstance(nested, dict):
                videos = nested.get("videos")

        if not isinstance(videos, list):
            return empty

        items = []
        seen = set()

        for video in videos:
            card = self._to_card(video)

            if not card:
                continue

            vid = str(video.get("_id") or "")

            if vid in seen:
                continue

            seen.add(vid)
            items.append(card)

        pagination = data.get("pagination") or {}

        if not pagination:
            nested = data.get("data")
            if isinstance(nested, dict):
                pagination = (
                    nested.get("pagination") or {}
                )

        if not isinstance(pagination, dict):
            pagination = {}

        has_next = pagination.get("hasNext")
        total_pages = pagination.get("totalPages")

        try:
            total_pages = int(total_pages)
        except (TypeError, ValueError):
            total_pages = 0

        if has_next is None:
            if total_pages:
                has_next = page < total_pages
            else:
                has_next = len(videos) >= limit

        if has_next:
            pagecount = max(
                page + 1, total_pages
            )
        else:
            pagecount = page

        try:
            total = int(
                pagination.get("total") or 0
            )
        except (TypeError, ValueError):
            total = 0

        return {
            "list": items,
            "page": page,
            "pagecount": pagecount,
            "limit": limit,
            "total": total,
        }

    def _api_list(self, path, params, page, limit):
        url = (
            HOST + path + "?"
            + U.urlencode(params)
        )

        data = self._request_json(url)

        return self._parse_list(
            data, page, limit
        )

    def homeContent(self, filter):
        return {
            "class": [
                {
                    "type_id": "all",
                    "type_name": "所有视频"
                },
                {
                    "type_id": "trending",
                    "type_name": "热门视频"
                },
                {
                    "type_id": "popular",
                    "type_name": "最受欢迎"
                }
            ]
        }

    def homeVideoContent(self):
        result = self._category_videos(
            "all", 1
        )
        return {
            "list": result.get("list", [])
        }

    def _category_videos(self, category, page):
        config = CATEGORIES.get(
            category,
            CATEGORIES["all"]
        )

        limit = config["limit"]

        params = {
            "limit": limit,
            "sort": config["sort"],
            "page": page,
            "skipCount": "true",
            "tagMode": "OR",
            "expandTags": "false",
        }

        if config.get("trending"):
            params["trending"] = "true"

        return self._api_list(
            "/api/videos",
            params,
            page,
            limit
        )

    def _author_videos(self, uploader_id, page):
        limit = 100

        params = {
            "uploader": uploader_id,
            "limit": limit,
            "page": page,
        }

        return self._api_list(
            "/api/videos",
            params,
            page,
            limit
        )

    def _tag_videos(self, tag, page):
        limit = 32

        params = {
            "limit": limit,
            "page": page,
            "tags": tag,
            "tagMode": "OR",
            "expandTags": "false",
        }

        return self._api_list(
            "/api/videos",
            params,
            page,
            limit
        )

    def categoryContent(self, tid, pg, filter, extend):
        page = safe_page(pg)
        tid = str(tid or "all")

        if tid.startswith("author:"):
            uploader_id = tid.split(":", 1)[1]
            return self._author_videos(
                uploader_id, page
            )

        if tid.startswith("tag:"):
            tag = U.unquote(
                tid.split(":", 1)[1]
            )
            return self._tag_videos(tag, page)

        aliases = {
            "/browse": "all",
            "/trending": "trending",
            "/popular": "popular",
        }

        tid = aliases.get(tid, tid)

        return self._category_videos(
            tid, page
        )

    def searchContent(self, key, quick, pg="1"):
        page = safe_page(pg)
        limit = 32

        key = str(key or "").strip()

        if not key:
            return {
                "list": [],
                "page": page,
                "pagecount": page
            }

        params = {
            "limit": limit,
            "page": page,
            "q": key,
        }

        return self._api_list(
            "/api/videos/search",
            params,
            page,
            limit
        )

    def _read_video_id(self, vod_id):
        vod_id = str(vod_id or "")

        if vod_id.startswith("pmv:"):
            info = decode_data(vod_id[4:])

            if info.get("_id"):
                return info

        # 兼容纯视频 ID。
        if re.fullmatch(
            r"[0-9a-fA-F]{24}", vod_id
        ):
            return getattr(
                self, "video_cache", {}
            ).get(vod_id, {})

        return {}

    def _entity_link(self, name, target):
        """生成 FongMi 可点击的分类链接。"""
        name = clean_name(name)

        if not name:
            return ""

        payload = {
            "id": target,
            "name": name,
            "type_flag": 1,
        }

        try:
            return self.link(name, payload)
        except Exception:
            return name

    def detailContent(self, ids):
        vod_id = (
            ids[0]
            if isinstance(ids, (list, tuple))
            else ids
        )

        info = self._read_video_id(vod_id)

        if not info:
            return {
                "list": [{
                    "vod_id": vod_id,
                    "vod_name": "视频信息不可用",
                    "vod_content": (
                        "无法从视频 ID 还原播放信息，"
                        "请从分类或搜索列表重新进入。"
                    )
                }]
            }

        title = info.get("title") or "未知标题"
        pic = info.get("thumbnailUrl") or ""
        mp4 = info.get("videoUrl") or ""

        uploader = info.get(
            "uploaderUsername"
        ) or "未知作者"

        uploader_id = info.get(
            "uploaderId"
        ) or ""

        tags = info.get("tags") or []

        content = []

        if uploader_id:
            author_link = self._entity_link(
                uploader,
                "author:" + uploader_id
            )
            content.append(
                "作者：" + author_link
            )
        else:
            content.append(
                "作者：" + uploader
            )

        if tags:
            tag_links = []

            for tag in tags:
                tag = str(tag).strip()

                if not tag:
                    continue

                tag_links.append(
                    self._entity_link(
                        tag,
                        "tag:" + U.quote(
                            tag, safe=""
                        )
                    )
                )

            content.append(
                "标签：" + "、".join(tag_links)
            )

        stars = info.get("starsTags") or []

        if stars:
            content.append(
                "人物：" + "、".join(
                    str(x) for x in stars
                )
            )

        duration = info.get("duration")

        if duration:
            content.append(
                "时长：" + str(duration)
            )

        content.append(
            "播放量：" + str(
                info.get("views", 0)
            )
        )

        content.append(
            "点赞数：" + str(
                info.get("likes", 0)
            )
        )

        width = info.get("width", 0)
        height = info.get("height", 0)

        if width and height:
            content.append(
                "分辨率：{}×{}".format(
                    width, height
                )
            )

        date = info.get("releaseDate") or ""

        if date:
            content.append(
                "发布日期：" + date[:10]
            )

        # 只添加当前视频，不添加相关推荐。
        if mp4:
            play_url = (
                "在线播放$" + mp4
            )
        else:
            play_url = ""

        vod = {
            "vod_id": vod_id,
            "vod_name": title,
            "vod_pic": pic,
            "vod_actor": uploader,
            "vod_director": uploader,
            "vod_content": "\n".join(content),
            "vod_play_from": (
                "PMVHaven" if mp4 else ""
            ),
            "vod_play_url": play_url,
        }

        return {
            "list": [vod]
        }

    def playerContent(self, flag, id, vipFlags):
        url = str(id or "").strip()

        if url.startswith("pmv:"):
            info = self._read_video_id(url)
            url = info.get("videoUrl") or ""

        if not url.startswith(
            ("https://", "http://")
        ):
            return {
                "parse": 1,
                "url": HOST,
            }

        return {
            "parse": 0,
            "url": url,
            "header": {
                "User-Agent": UA,
                "Referer": HOST + "/",
                "Origin": HOST,
            }
        }

    def localProxy(self, param):
        return None
