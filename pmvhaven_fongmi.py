
# -*- coding: utf-8 -*-
import re
import json
import time
import base64
import urllib.parse as U
import urllib.request as R
import urllib.error as E

from base.spider import Spider as BaseSpider


HOST = "https://pmvhaven.com"
CLOUD = (
    "https://pmvhavencloud."
    "s3.eu-west-par.io.cloud.ovh.net"
)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/156.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": UA,
    "Referer": HOST + "/",
    "Origin": HOST,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

PLAY_HEADERS = {
    "User-Agent": UA,
    "Referer": HOST + "/",
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
    except (ValueError, TypeError):
        return 1


def encode_data(data):
    raw = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":")
    ).encode("utf-8")

    return base64.urlsafe_b64encode(
        raw
    ).decode("ascii").rstrip("=")


def decode_data(value):
    try:
        value = str(value)
        value += "=" * (-len(value) % 4)

        raw = base64.urlsafe_b64decode(
            value.encode("ascii")
        )

        result = json.loads(raw.decode("utf-8"))

        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def clean_text(value):
    return re.sub(
        r"[$#\r\n]",
        " ",
        str(value or "")
    ).strip()


def format_views(value):
    try:
        value = int(value)
    except (ValueError, TypeError):
        return "0"

    if value >= 100000000:
        return "{:.1f}亿".format(value / 100000000)

    if value >= 10000:
        return "{:.1f}万".format(value / 10000)

    return str(value)


class Spider(BaseSpider):

    def getName(self):
        return "PMVHaven"

    def init(self, extend=""):
        self.video_cache = {}
        self.last_error = ""

    def destroy(self):
        pass

    def isVideoFormat(self, url):
        return bool(re.search(
            r"\.(mp4|m3u8)(?:[?#]|$)",
            str(url),
            re.I
        ))

    def manualVideoCheck(self):
        return False

    # ========================================
    # HTTP 请求
    # ========================================

    def _request(self, url, accept=None, timeout=15):
        headers = dict(HEADERS)

        if accept:
            headers["Accept"] = accept

        req = R.Request(url, headers=headers)

        try:
            with R.urlopen(req, timeout=timeout) as response:
                content = response.read()

            self.last_error = ""

            return content.decode("utf-8", "replace")

        except E.HTTPError as e:
            self.last_error = "HTTP {}: {}".format(
                e.code, url
            )

        except Exception as e:
            self.last_error = "{}: {}".format(
                type(e).__name__, str(e)
            )

        return ""

    def _request_json(self, url):
        text = self._request(url)

        if not text:
            return {}

        try:
            data = json.loads(text)

            if isinstance(data, dict):
                return data

            self.last_error = "API 返回的数据不是 JSON 对象"

        except Exception as e:
            self.last_error = "JSON 解析失败: {}".format(e)

        return {}

    # ========================================
    # 视频信息
    # ========================================

    def _video_info(self, video):
        if not isinstance(video, dict):
            return None

        vid = str(video.get("_id") or "").strip()
        title = clean_text(video.get("title"))

        if not vid or not title:
            return None

        sizes = video.get("thumbnailSizes") or {}

        if not isinstance(sizes, dict):
            sizes = {}

        lg = sizes.get("lg") or {}

        if not isinstance(lg, dict):
            lg = {}

        pic = (
            video.get("thumbnailUrl")
            or lg.get("url")
            or CLOUD + "/thumbnails/" + vid + "/thumb_lg.webp"
        )

        tags = video.get("tags") or []
        stars = video.get("starsTags") or []

        if not isinstance(tags, list):
            tags = []

        if not isinstance(stars, list):
            stars = []

        return {
            "_id": vid,
            "title": title,
            "thumbnailUrl": pic,
            "videoUrl": video.get("videoUrl") or "",
            "uploaderId": str(video.get("uploaderId") or ""),
            "uploaderUsername": (
                video.get("uploaderUsername")
                or video.get("uploader")
                or ""
            ),
            "tags": tags,
            "starsTags": stars,
            "duration": video.get("duration") or "",
            "views": video.get("views") or 0,
            "likes": video.get("likes") or 0,
            "releaseDate": video.get("releaseDate") or "",
            "width": video.get("width") or 0,
            "height": video.get("height") or 0,
            "hlsEnabled": video.get("hlsEnabled"),
            "hlsStatus": video.get("hlsStatus") or "",
        }

    def _to_card(self, video):
        info = self._video_info(video)

        if not info:
            return None

        if not hasattr(self, "video_cache"):
            self.video_cache = {}

        vid = info["_id"]
        self.video_cache[vid] = info

        vod_id = "pmv:" + encode_data(info)

        remarks = format_views(info["views"]) + "播放"

        if info["duration"]:
            remarks = "{} | {}".format(
                info["duration"], remarks
            )

        return {
            "vod_id": vod_id,
            "vod_name": info["title"],
            "vod_pic": info["thumbnailUrl"],
            "vod_remarks": remarks,
            "style": {
                "type": "rect",
                "ratio": 1.78,
            }
        }

    # ========================================
    # 列表解析与分页
    # ========================================

    def _parse_list(self, data, page, limit):
        videos = data.get("videos") or data.get("results") or data.get("items")
        pagination = data.get("pagination") or {}

        if not isinstance(videos, list):
            nested = data.get("data")

            if isinstance(nested, dict):
                videos = nested.get("videos") or nested.get("results") or nested.get("items")
                pagination = (
                    nested.get("pagination") or pagination
                )

        if not isinstance(videos, list):
            videos = []

        if not isinstance(pagination, dict):
            pagination = {}

        items = []
        seen = set()

        for video in videos:
            if not isinstance(video, dict):
                continue

            vid = str(video.get("_id") or "")

            if not vid or vid in seen:
                continue

            card = self._to_card(video)

            if card:
                seen.add(vid)
                items.append(card)

        has_next = pagination.get("hasNext")

        try:
            total_pages = int(
                pagination.get("totalPages") or 0
            )
        except (ValueError, TypeError):
            total_pages = 0

        if has_next is None:
            if total_pages:
                has_next = page < total_pages
            else:
                has_next = len(videos) >= limit

        if isinstance(has_next, str):
            has_next = has_next.lower() == "true"

        if has_next:
            pagecount = max(page + 1, total_pages)
        else:
            pagecount = page

        try:
            total = int(pagination.get("total") or 0)
        except (ValueError, TypeError):
            total = 0

        return {
            "list": items,
            "page": page,
            "pagecount": pagecount,
            "limit": limit,
            "total": total,
        }

    def _api_list(self, path, params, page, limit):
        url = HOST + path + "?" + U.urlencode(params)

        data = self._request_json(url)

        result = self._parse_list(data, page, limit)

        if not data and self.last_error:
            result["error"] = self.last_error

        return result

    # ========================================
    # 首页
    # ========================================

    def homeContent(self, filter):
        return {
            "class": [
                {
                    "type_id": "all",
                    "type_name": "所有视频",
                },
                {
                    "type_id": "trending",
                    "type_name": "热门视频",
                },
                {
                    "type_id": "popular",
                    "type_name": "最受欢迎",
                },
            ]
        }

    def homeVideoContent(self):
        return {"list": []}

    # ========================================
    # 分类列表
    # ========================================

    def _category_videos(self, category, page):
        config = CATEGORIES.get(
            category, CATEGORIES["all"]
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
            "/api/videos", params, page, limit
        )

    def _author_videos(self, uploader_id, page):
        limit = 100

        params = {
            "uploader": uploader_id,
            "limit": limit,
            "page": page,
        }

        return self._api_list(
            "/api/videos", params, page, limit
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
            "/api/videos", params, page, limit
        )

    def categoryContent(self, tid, pg, filter, extend):
        page = safe_page(pg)
        tid = str(tid or "all")

        if tid.startswith("author:"):
            uploader_id = tid.split(":", 1)[1]
            return self._author_videos(uploader_id, page)

        if tid.startswith("tag:"):
            tag = U.unquote(tid.split(":", 1)[1])
            return self._tag_videos(tag, page)

        aliases = {
            "/browse": "all",
            "/trending": "trending",
            "/popular": "popular",
        }

        tid = aliases.get(tid, tid)

        return self._category_videos(tid, page)

    # ========================================
    # 搜索
    # ========================================

    def searchContent(self, key, quick, pg="1"):
        page = safe_page(pg)
        key = str(key or "").strip()

        if not key:
            return {
                "list": [],
                "page": page,
                "pagecount": page,
            }

        limit = 32

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

    # ========================================
    # 视频 ID
    # ========================================

    def _read_video_id(self, vod_id):
        vod_id = str(vod_id or "")

        if vod_id.startswith("pmv:"):
            info = decode_data(vod_id[4:])

            if info.get("_id"):
                return info

        if re.fullmatch(r"[0-9a-fA-F]{24}", vod_id):
            cache = getattr(self, "video_cache", {})
            return cache.get(vod_id, {"_id": vod_id})

        return {}

    # ========================================
    # 作者、标签点击链接
    # ========================================

    def _entity_link(self, name, target):
        name = clean_text(name)

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

    # ========================================
    # 详情数据补全（不依赖内存缓存）
    # ========================================

    def _extract_video(self, data):
        if not isinstance(data, dict):
            return {}
        for key in ("video", "data", "result"):
            obj = data.get(key)
            if isinstance(obj, dict):
                nested = self._extract_video(obj)
                if nested:
                    return nested
        if data.get("_id") or data.get("videoUrl"):
            return data
        return {}

    def _fetch_video(self, vid):
        """仅通过详情接口补全字段；不使用 ID 拼接任何播放地址。"""
        vid = str(vid or "").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{24}", vid):
            return {}
        # 不同站点部署可能采用不同详情路由，逐个验证返回数据。
        for path in ("/api/videos/", "/api/video/"):
            data = self._request_json(HOST + path + U.quote(vid, safe=""))
            video = self._extract_video(data)
            if video and str(video.get("_id") or vid) == vid:
                normalized = self._video_info(dict(video, _id=vid))
                if normalized:
                    return normalized
                return video
        return {}

    def _resolve_info(self, vod_id):
        info = self._read_video_id(vod_id)
        vid = str(info.get("_id") or "").strip()
        if not vid and re.fullmatch(r"[0-9a-fA-F]{24}", str(vod_id or "")):
            vid = str(vod_id)
        if not vid:
            return info
        # 搜索接口的 videoUrl 可能缺失，必须尝试详情接口补全。
        if not self._valid_mp4(info.get("videoUrl")):
            fetched = self._fetch_video(vid)
            if fetched:
                info = dict(info, **{k: v for k, v in fetched.items() if v not in (None, "", [], {})})
        if info:
            if not hasattr(self, "video_cache"):
                self.video_cache = {}
            self.video_cache[vid] = info
        return info

    def _valid_mp4(self, url):
        url = str(url or "").strip()
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = U.urljoin(HOST, url)
        return url.startswith(("https://", "http://")) and bool(U.urlsplit(url).netloc)

    def _normalize_video_url(self, url):
        url = str(url or "").strip()
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return U.urljoin(HOST, url)
        return url

    # ========================================
    # 构造 FongMi 播放线路
    # ========================================

    def _build_play_sources(self, info):
        """只使用 API 返回的原始 MP4 地址，不请求 HLS。"""
        mp4 = self._normalize_video_url(info.get("videoUrl"))
        if self._valid_mp4(mp4):
            return "原始MP4", "原始播放$" + mp4
        return "", ""

    # ========================================
    # 视频详情
    # ========================================

    def detailContent(self, ids):
        vod_id = (
            ids[0]
            if isinstance(ids, (list, tuple))
            else ids
        )

        info = self._resolve_info(vod_id)

        if not info:
            return {
                "list": [{
                    "vod_id": vod_id,
                    "vod_name": "视频信息不可用",
                    "vod_content": (
                        "无法获取视频信息，"
                        "请从分类或搜索列表重新进入。"
                    ),
                }]
            }

        title = info.get("title", "")
        pic = info.get("thumbnailUrl", "")

        uploader = (
            info.get("uploaderUsername")
            or "未知作者"
        )

        uploader_id = info.get("uploaderId", "")

        tags = info.get("tags", [])
        stars = info.get("starsTags", [])

        content = []

        # 作者可点击。
        if uploader_id:
            author_link = self._entity_link(
                uploader,
                "author:" + uploader_id
            )

            content.append("作者：" + author_link)
        else:
            content.append("作者：" + uploader)

        # 标签可点击。
        if tags:
            tag_links = []

            for tag in tags:
                tag = str(tag).strip()

                if not tag:
                    continue

                target = (
                    "tag:"
                    + U.quote(tag, safe="")
                )

                tag_links.append(
                    self._entity_link(tag, target)
                )

            if tag_links:
                content.append(
                    "标签：" + "、".join(tag_links)
                )

        if stars:
            content.append(
                "人物："
                + "、".join(str(x) for x in stars)
            )

        duration = info.get("duration", "")

        if duration:
            content.append(
                "时长：" + str(duration)
            )

        content.append(
            "播放量：" + str(info.get("views", 0))
        )

        content.append(
            "点赞数：" + str(info.get("likes", 0))
        )

        width = info.get("width", 0)
        height = info.get("height", 0)

        if width and height:
            content.append(
                "原始分辨率：{}×{}".format(
                    width,
                    height
                )
            )

        date = str(info.get("releaseDate") or "")

        if date:
            content.append(
                "发布日期：" + date[:10]
            )

        play_from, play_url = self._build_play_sources(
            info
        )

        vod = {
            "vod_id": vod_id,
            "vod_name": title,
            "vod_pic": pic,
            "vod_actor": uploader,
            "vod_director": uploader,
            "vod_content": "\n".join(content),
            "vod_play_from": play_from,
            "vod_play_url": play_url,
        }

        return {"list": [vod]}

    # ========================================
    # 播放器
    # ========================================

    def playerContent(self, flag, id, vipFlags):
        url = str(id or "").strip()

        if url.startswith("pmv:"):
            info = self._resolve_info(url)
            url = self._normalize_video_url(info.get("videoUrl"))
        elif re.fullmatch(r"[0-9a-fA-F]{24}", url):
            info = self._resolve_info(url)
            url = self._normalize_video_url(info.get("videoUrl"))
        else:
            url = self._normalize_video_url(url)

        if not self._valid_mp4(url):
            return {
                "parse": 0,
                "url": "",
                "msg": "播放地址无效或已失效",
            }

        return {
            "parse": 0,
            "url": url,
            "header": PLAY_HEADERS,
        }

    def localProxy(self, param):
        return None
