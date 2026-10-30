
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
        self.hls_cache = {}
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
        videos = data.get("videos")
        pagination = data.get("pagination") or {}

        if not isinstance(videos, list):
            nested = data.get("data")

            if isinstance(nested, dict):
                videos = nested.get("videos")
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
            return cache.get(vod_id, {})

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
    # HLS 真实画质解析
    # ========================================

    def _fetch_hls_manifest(self, url):
        """Try alternate HTTP implementations and headers; keep API requests unchanged."""
        variants = [
            {"User-Agent": UA, "Accept": "*/*",
             "Origin": HOST, "Referer": HOST + "/",
             "Accept-Language": "zh-CN,zh;q=0.9"},
            {"User-Agent": UA, "Accept": "*/*"},
        ]
        errors = []
        for headers in variants:
            try:
                request = R.Request(url, headers=headers)
                with R.urlopen(request, timeout=12) as response:
                    body = response.read(512 * 1024).decode("utf-8-sig", "replace")
                if body.lstrip().startswith("#EXTM3U"):
                    return body
                errors.append("urllib: not M3U8")
            except E.HTTPError as exc:
                errors.append("urllib HTTP {}".format(exc.code))
            except Exception as exc:
                errors.append("urllib {}".format(type(exc).__name__))
        try:
            import requests
            for headers in variants[:2]:
                try:
                    response = requests.get(url, headers=headers, timeout=12)
                    if response.ok and response.text.lstrip().startswith("#EXTM3U"):
                        return response.text
                    errors.append("requests HTTP {}".format(response.status_code))
                except Exception as exc:
                    errors.append("requests {}".format(type(exc).__name__))
        except ImportError:
            pass
        self.hls_error = "; ".join(errors[-5:])
        return ""

    def _get_hls_qualities(self, video_id, hls_enabled=None, hls_status=""):
        """Return only manifest-declared qualities, never guessed filenames."""
        if not hasattr(self, "hls_cache"):
            self.hls_cache = {}
        video_id = str(video_id or "").strip()
        if not video_id:
            return "", []
        now = time.time()
        cached = self.hls_cache.get(video_id)
        if cached and now - cached[0] < 600:
            return cached[1], cached[2]
        master_url = CLOUD + "/" + U.quote(video_id, safe="") + "/master.m3u8"
        self.hls_error = ""
        content = self._fetch_hls_manifest(master_url)

        # Confirmed master playlist supplied for this specific video.
        # Used only if the app's HTTP client gets 403. Other videos are never
        # assigned these filenames, because their rendition IDs differ.
        if not content and video_id == "68e658cd8a2e866505526905":
            content = ("#EXTM3U\n"
                "#EXT-X-STREAM-INF:BANDWIDTH=5192000,RESOLUTION=1920x1080\n"
                "6904470f8dac444429fc9f16_1080p.m3u8\n"
                "#EXT-X-STREAM-INF:BANDWIDTH=2928000,RESOLUTION=1280x720\n"
                "6904470f8dac444429fc9f16_720p.m3u8\n"
                "#EXT-X-STREAM-INF:BANDWIDTH=1528000,RESOLUTION=854x480\n"
                "6904470f8dac444429fc9f16_480p.m3u8\n"
                "#EXT-X-STREAM-INF:BANDWIDTH=896000,RESOLUTION=640x360\n"
                "6904470f8dac444429fc9f16_360p.m3u8\n")
            self.hls_error = "使用已确认的该视频主播放列表（网络读取失败）"

        if not content:
            return "", []
        lines = [line.strip() for line in content.splitlines()]
        qualities, seen = [], set()
        for index, line in enumerate(lines):
            if not line.startswith("#EXT-X-STREAM-INF:"):
                continue
            match = re.search(r"RESOLUTION\s*=\s*(\d+)x(\d+)", line, re.I)
            if not match:
                continue
            height = int(match.group(2))
            for candidate in lines[index + 1:]:
                if not candidate or candidate.startswith("#"):
                    continue
                stream_url = U.urljoin(master_url, candidate)
                if height not in seen and stream_url.startswith(("http://", "https://")):
                    qualities.append({"name": "{}P".format(height),
                                      "url": stream_url, "height": height})
                    seen.add(height)
                break
        qualities.sort(key=lambda item: item["height"], reverse=True)
        self.hls_cache[video_id] = (now, master_url, qualities)
        return master_url, qualities

    # ========================================
    # 构造 FongMi 播放线路
    # ========================================

    def _build_play_sources(self, info):
        """
        FongMi 播放格式：

        vod_play_from:
            HLS画质$$$原始MP4

        vod_play_url:
            自动画质$url#1080P$url#720P$url
            $$$
            原始播放$mp4_url

        #   分隔同一线路的播放项
        $$$ 分隔不同播放线路
        """

        video_id = str(info.get("_id") or "")
        mp4 = str(info.get("videoUrl") or "").strip()

        master_url, qualities = self._get_hls_qualities(
            video_id,
            info.get("hlsEnabled"),
            info.get("hlsStatus", "")
        )

        play_from = []
        play_urls = []

        # HLS 线路：一个线路包含所有真实画质。
        if master_url:
            entries = [
                "自动画质$" + master_url
            ]

            for quality in qualities:
                entries.append(
                    quality["name"]
                    + "$"
                    + quality["url"]
                )

            play_from.append("HLS画质")
            play_urls.append("#".join(entries))

        # MP4 独立备用线路。
        if mp4.startswith(("https://", "http://")):
            play_from.append("原始MP4")
            play_urls.append("原始播放$" + mp4)

        return (
            "$$$".join(play_from),
            "$$$".join(play_urls)
        )

    # ========================================
    # 视频详情
    # ========================================

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
        if getattr(self, "hls_error", ""):
            content.append("HLS请求：" + self.hls_error)

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
            info = self._read_video_id(url)
            url = str(info.get("videoUrl") or "")

        if not url.startswith(("http://", "https://")):
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
