
# -*- coding: utf-8 -*-

import re
import json
import base64
import urllib.parse as U
import urllib.request as R

from base.spider import Spider as BaseSpider


HOST = "https://pmvhaven.com"

CLOUD = (
    "https://pmvhavencloud."
    "s3.eu-west-par.io.cloud.ovh.net"
)

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
    except (TypeError, ValueError):
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

        result = json.loads(
            raw.decode("utf-8")
        )

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
    except (TypeError, ValueError):
        return "0"

    if value >= 100000000:
        return "{:.1f}亿".format(
            value / 100000000
        )

    if value >= 10000:
        return "{:.1f}万".format(
            value / 10000
        )

    return str(value)


class Spider(BaseSpider):

    def getName(self):
        return "PMVHaven"

    def init(self, extend=""):
        self.video_cache = {}
        self.hls_cache = {}
        self.last_error = ""

    def destroy(self):
        pass

    def isVideoFormat(self, url):
        return bool(
            re.search(
                r"\.(mp4|m3u8)(\?|$)",
                str(url),
                re.I
            )
        )

    def manualVideoCheck(self):
        return False

    # =========================================
    # HTTP
    # =========================================

    def _request(self, url, accept=None):
        headers = dict(HEADERS)

        if accept:
            headers["Accept"] = accept

        req = R.Request(
            url,
            headers=headers
        )

        try:
            with R.urlopen(
                req,
                timeout=15
            ) as response:

                content = response.read()

            self.last_error = ""

            return content.decode(
                "utf-8",
                "replace"
            )

        except Exception as e:
            self.last_error = str(e)
            return ""

    def _request_json(self, url):
        text = self._request(url)

        if not text:
            return {}

        try:
            data = json.loads(text)

            if isinstance(data, dict):
                return data

        except Exception:
            pass

        return {}

    # =========================================
    # 视频信息
    # =========================================

    def _video_info(self, video):
        if not isinstance(video, dict):
            return None

        vid = str(
            video.get("_id") or ""
        ).strip()

        title = clean_text(
            video.get("title")
        )

        if not vid or not title:
            return None

        sizes = (
            video.get("thumbnailSizes")
            or {}
        )

        lg = sizes.get("lg") or {}

        pic = (
            video.get("thumbnailUrl")
            or lg.get("url")
            or (
                CLOUD
                + "/thumbnails/"
                + vid
                + "/thumb_lg.webp"
            )
        )

        tags = video.get("tags") or []

        if not isinstance(tags, list):
            tags = []

        stars = (
            video.get("starsTags")
            or []
        )

        if not isinstance(stars, list):
            stars = []

        info = {
            "_id": vid,
            "title": title,
            "thumbnailUrl": pic,
            "videoUrl": (
                video.get("videoUrl")
                or ""
            ),
            "uploaderId": str(
                video.get("uploaderId")
                or ""
            ),
            "uploaderUsername": (
                video.get("uploaderUsername")
                or video.get("uploader")
                or ""
            ),
            "tags": tags,
            "starsTags": stars,
            "duration": (
                video.get("duration")
                or ""
            ),
            "views": (
                video.get("views")
                or 0
            ),
            "likes": (
                video.get("likes")
                or 0
            ),
            "releaseDate": (
                video.get("releaseDate")
                or ""
            ),
            "width": (
                video.get("width")
                or 0
            ),
            "height": (
                video.get("height")
                or 0
            ),
            "hlsEnabled": (
                video.get("hlsEnabled")
            ),
            "hlsStatus": (
                video.get("hlsStatus")
                or ""
            ),
        }

        return info

    def _to_card(self, video):
        info = self._video_info(video)

        if not info:
            return None

        if not hasattr(self, "video_cache"):
            self.video_cache = {}

        vid = info["_id"]

        self.video_cache[vid] = info

        vod_id = (
            "pmv:"
            + encode_data(info)
        )

        duration = info["duration"]

        remarks = (
            format_views(info["views"])
            + "播放"
        )

        if duration:
            remarks = (
                str(duration)
                + " | "
                + remarks
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

    # =========================================
    # 统一列表解析
    # =========================================

    def _parse_list(self, data, page, limit):
        videos = data.get("videos")

        pagination = (
            data.get("pagination")
            or {}
        )

        if not isinstance(videos, list):
            nested = data.get("data")

            if isinstance(nested, dict):
                videos = nested.get("videos")

                pagination = (
                    nested.get("pagination")
                    or pagination
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

            vid = str(
                video.get("_id")
                or ""
            )

            if not vid or vid in seen:
                continue

            card = self._to_card(video)

            if card:
                seen.add(vid)
                items.append(card)

        has_next = pagination.get(
            "hasNext"
        )

        try:
            total_pages = int(
                pagination.get("totalPages")
                or 0
            )
        except Exception:
            total_pages = 0

        if has_next is None:
            if total_pages:
                has_next = (
                    page < total_pages
                )
            else:
                has_next = (
                    len(videos) >= limit
                )

        if has_next:
            pagecount = max(
                page + 1,
                total_pages
            )
        else:
            pagecount = page

        try:
            total = int(
                pagination.get("total")
                or 0
            )
        except Exception:
            total = 0

        return {
            "list": items,
            "page": page,
            "pagecount": pagecount,
            "limit": limit,
            "total": total,
        }

    def _api_list(
        self,
        path,
        params,
        page,
        limit
    ):
        url = (
            HOST
            + path
            + "?"
            + U.urlencode(params)
        )

        data = self._request_json(url)

        return self._parse_list(
            data,
            page,
            limit
        )

    # =========================================
    # 首页
    # =========================================

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
        # 不再提供首页推荐视频。
        return {
            "list": []
        }

    # =========================================
    # 分类列表
    # =========================================

    def _category_videos(
        self,
        category,
        page
    ):
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

    # =========================================
    # 作者列表
    # =========================================

    def _author_videos(
        self,
        uploader_id,
        page
    ):
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

    # =========================================
    # 标签列表
    # =========================================

    def _tag_videos(
        self,
        tag,
        page
    ):
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

    def categoryContent(
        self,
        tid,
        pg,
        filter,
        extend
    ):
        page = safe_page(pg)

        tid = str(
            tid or "all"
        )

        if tid.startswith("author:"):
            uploader_id = tid.split(
                ":", 1
            )[1]

            return self._author_videos(
                uploader_id,
                page
            )

        if tid.startswith("tag:"):
            tag = U.unquote(
                tid.split(":", 1)[1]
            )

            return self._tag_videos(
                tag,
                page
            )

        aliases = {
            "/browse": "all",
            "/trending": "trending",
            "/popular": "popular",
        }

        tid = aliases.get(
            tid,
            tid
        )

        return self._category_videos(
            tid,
            page
        )

    # =========================================
    # 搜索
    # =========================================

    def searchContent(
        self,
        key,
        quick,
        pg="1"
    ):
        page = safe_page(pg)

        key = str(
            key or ""
        ).strip()

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

    # =========================================
    # 视频 ID 解析
    # =========================================

    def _read_video_id(self, vod_id):
        vod_id = str(
            vod_id or ""
        )

        if vod_id.startswith("pmv:"):
            info = decode_data(
                vod_id[4:]
            )

            if info.get("_id"):
                return info

        if re.fullmatch(
            r"[0-9a-fA-F]{24}",
            vod_id
        ):
            cache = getattr(
                self,
                "video_cache",
                {}
            )

            return cache.get(
                vod_id,
                {}
            )

        return {}

    # =========================================
    # FongMi 可点击链接
    # =========================================

    def _entity_link(
        self,
        name,
        target
    ):
        name = clean_text(name)

        if not name:
            return ""

        payload = {
            "id": target,
            "name": name,
            "type_flag": 1,
        }

        try:
            return self.link(
                name,
                payload
            )
        except Exception:
            return name

    # =========================================
    # HLS 多画质解析
    # =========================================

    def _get_hls_qualities(
        self,
        video_id,
        hls_enabled=None,
        hls_status=""
    ):
        """
        返回：
        master_url, qualities

        qualities 示例：
        [
            {
                "name": "1080P",
                "url": "...1080p.m3u8",
                "height": 1080
            }
        ]
        """

        if not hasattr(
            self,
            "hls_cache"
        ):
            self.hls_cache = {}

        if video_id in self.hls_cache:
            return self.hls_cache[
                video_id
            ]

        master_url = (
            CLOUD
            + "/"
            + video_id
            + "/master.m3u8"
        )

        # 明确未启用 HLS 时跳过。
        if hls_enabled is False:
            result = ("", [])
            self.hls_cache[
                video_id
            ] = result
            return result

        content = self._request(
            master_url,
            accept=(
                "application/vnd.apple.mpegurl,"
                "application/x-mpegURL,"
                "text/plain,*/*"
            )
        )

        if not content.startswith(
            "#EXTM3U"
        ):
            result = ("", [])
            self.hls_cache[
                video_id
            ] = result
            return result

        lines = [
            line.strip()
            for line in content.splitlines()
        ]

        qualities = []

        for index, line in enumerate(lines):
            if not line.startswith(
                "#EXT-X-STREAM-INF:"
            ):
                continue

            match = re.search(
                r"RESOLUTION=(\d+)x(\d+)",
                line
            )

            if not match:
                continue

            height = int(
                match.group(2)
            )

            # 读取该画质对应的实际文件名。
            for next_line in lines[index + 1:]:
                if not next_line:
                    continue

                if next_line.startswith("#"):
                    continue

                stream_url = U.urljoin(
                    master_url,
                    next_line
                )

                qualities.append({
                    "name": "{}P".format(
                        height
                    ),
                    "url": stream_url,
                    "height": height,
                })

                break

        # 高画质优先。
        qualities.sort(
            key=lambda x: x["height"],
            reverse=True
        )

        unique = []
        seen = set()

        for item in qualities:
            if item["name"] in seen:
                continue

            seen.add(
                item["name"]
            )

            unique.append(item)

        result = (
            master_url,
            unique
        )

        self.hls_cache[
            video_id
        ] = result

        return result

    # =========================================
    # 构造播放线路
    # =========================================

    def _build_play_sources(self, info):
        video_id = info.get(
            "_id", ""
        )

        mp4 = info.get(
            "videoUrl", ""
        )

        hls_enabled = info.get(
            "hlsEnabled"
        )

        hls_status = info.get(
            "hlsStatus", ""
        )

        master_url, qualities = (
            self._get_hls_qualities(
                video_id,
                hls_enabled,
                hls_status
            )
        )

        play_from = []
        play_urls = []

        # 真实 HLS 主列表。
        if master_url:
            play_from.append(
                "自动画质"
            )

            play_urls.append(
                "自动播放$"
                + master_url
            )

            # 只有实际存在的画质才显示。
            for quality in qualities:
                name = quality["name"]
                url = quality["url"]

                play_from.append(name)

                play_urls.append(
                    name + "$" + url
                )

        # 原始 MP4 备用。
        if mp4:
            play_from.append(
                "原始MP4"
            )

            play_urls.append(
                "原始播放$" + mp4
            )

        return (
            "$$$".join(play_from),
            "$$$".join(play_urls)
        )

    # =========================================
    # 视频详情
    # =========================================

    def detailContent(self, ids):
        vod_id = (
            ids[0]
            if isinstance(
                ids,
                (list, tuple)
            )
            else ids
        )

        info = self._read_video_id(
            vod_id
        )

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

        title = info.get(
            "title", ""
        )

        pic = info.get(
            "thumbnailUrl", ""
        )

        uploader = info.get(
            "uploaderUsername"
        ) or "未知作者"

        uploader_id = info.get(
            "uploaderId", ""
        )

        tags = info.get(
            "tags", []
        )

        stars = info.get(
            "starsTags", []
        )

        content = []

        # 作者可点击。
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

        # 标签可点击。
        if tags:
            tag_links = []

            for tag in tags:
                tag = str(
                    tag
                ).strip()

                if not tag:
                    continue

                target = (
                    "tag:"
                    + U.quote(
                        tag,
                        safe=""
                    )
                )

                tag_links.append(
                    self._entity_link(
                        tag,
                        target
                    )
                )

            if tag_links:
                content.append(
                    "标签："
                    + "、".join(tag_links)
                )

        if stars:
            content.append(
                "人物："
                + "、".join(
                    str(x)
                    for x in stars
                )
            )

        duration = info.get(
            "duration", ""
        )

        if duration:
            content.append(
                "时长："
                + str(duration)
            )

        content.append(
            "播放量："
            + str(
                info.get("views", 0)
            )
        )

        content.append(
            "点赞数："
            + str(
                info.get("likes", 0)
            )
        )

        width = info.get(
            "width", 0
        )

        height = info.get(
            "height", 0
        )

        if width and height:
            content.append(
                "原始分辨率："
                + "{}×{}".format(
                    width,
                    height
                )
            )

        date = info.get(
            "releaseDate", ""
        )

        if date:
            content.append(
                "发布日期："
                + date[:10]
            )

        play_from, play_url = (
            self._build_play_sources(
                info
            )
        )

        vod = {
            "vod_id": vod_id,
            "vod_name": title,
            "vod_pic": pic,
            "vod_actor": uploader,
            "vod_director": uploader,
            "vod_content": "\n".join(
                content
            ),
            "vod_play_from": play_from,
            "vod_play_url": play_url,
        }

        return {
            "list": [vod]
        }

    # =========================================
    # 播放器
    # =========================================

    def playerContent(
        self,
        flag,
        id,
        vipFlags
    ):
        url = str(
            id or ""
        ).strip()

        if url.startswith("pmv:"):
            info = self._read_video_id(
                url
            )

            url = info.get(
                "videoUrl", ""
            )

        if not url.startswith(
            ("http://", "https://")
        ):
            return {
                "parse": 1,
                "url": HOST,
            }

        return {
            "parse": 0,
            "url": url,
            "header": PLAY_HEADERS,
        }

    def localProxy(self, param):
        return None
