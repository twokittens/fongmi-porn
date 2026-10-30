
# -*- coding: utf-8 -*-
"""
PMVHaven FongMi Python Spider

功能：
1. 横版视频封面（16:9）
2. 正确提取视频标题
3. 过滤作者头像
4. 所有视频 / 热门视频 / 最受欢迎
5. 搜索与分页
6. 创作者和标签点击跳转
7. 1080P 优先播放
8. 相关视频连续播放
"""

import re
import json
import html
import urllib.parse
import urllib.request
from html.parser import HTMLParser

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider(object):
        pass


HOST = "https://pmvhaven.com"

UA = (
    "Mozilla/5.0 (Linux; Android 13) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)

HEADERS = {
    "User-Agent": UA,
    "Referer": HOST + "/",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*"
}

THUMB = (
    "https://pmvhavencloud.s3.eu-west-par.io.cloud.ovh.net/"
    "thumbnails/{}/thumb_lg.webp"
)

LANDSCAPE_STYLE = {
    "type": "rect",
    "ratio": 1.78
}

VIDEO_PATTERN = re.compile(
    r"^/video/[^/?#]+_([a-fA-F0-9]{24})/?$"
)


# ============================================================
# 网络请求
# ============================================================

def absolute(url):
    return urllib.parse.urljoin(
        HOST + "/",
        html.unescape(str(url or ""))
    )


def canonical(url):
    parsed = urllib.parse.urlsplit(absolute(url))

    return urllib.parse.urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        "",
        ""
    ))


def request(url, timeout=12, headers=None, max_bytes=3000000):
    h = dict(HEADERS)

    if headers:
        h.update(headers)

    req = urllib.request.Request(
        absolute(url),
        headers=h
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(max_bytes)


def fetch(url, timeout=12):
    return request(
        url,
        timeout=timeout
    ).decode("utf-8", "replace")


def clean(value):
    value = re.sub(
        r"<[^>]+>",
        " ",
        str(value or "")
    )

    return re.sub(
        r"\s+",
        " ",
        html.unescape(value)
    ).strip()


def video_key(url):
    path = urllib.parse.urlsplit(
        absolute(url)
    ).path

    match = VIDEO_PATTERN.fullmatch(path)

    return match.group(1).lower() if match else ""


def thumbnail(url):
    key = video_key(url)

    if not key:
        return ""

    return THUMB.format(key)


def valid_video(url):
    parsed = urllib.parse.urlsplit(absolute(url))

    if parsed.hostname not in (
        "pmvhaven.com",
        "www.pmvhaven.com"
    ):
        return False

    return bool(
        VIDEO_PATTERN.fullmatch(parsed.path)
    )


# ============================================================
# 视频卡片解析
# ============================================================

class CardParser(HTMLParser):

    def __init__(self):
        super().__init__(convert_charrefs=True)

        self.cards = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)

        if tag == "a":
            href = html.unescape(
                a.get("href", "")
            )

            valid = valid_video(href)

            self.stack.append({
                "valid": valid,
                "url": canonical(href) if valid else "",
                "title": "",
                "pic": "",
                "text": []
            })

            return

        if tag == "img" and self.stack:
            card = self.stack[-1]

            if not card["valid"]:
                return

            key = video_key(card["url"])

            if not key:
                return

            sources = [
                a.get("data-src", ""),
                a.get("src", ""),
                a.get("data-original", ""),
                a.get("data-lazy-src", "")
            ]

            srcset = a.get("srcset", "")

            if srcset:
                sources.extend(
                    x.strip().split(" ")[0]
                    for x in srcset.split(",")
                )

            for src in sources:
                src = html.unescape(src)

                match = re.search(
                    r"/thumbnails/([a-fA-F0-9]{24})/"
                    r"thumb_lg\.webp(?:\?|$)",
                    src,
                    re.I
                )

                if not match:
                    continue

                if match.group(1).lower() != key:
                    continue

                card["pic"] = absolute(src)

                alt = clean(a.get("alt", ""))

                if alt:
                    card["title"] = alt

                break

    def handle_data(self, data):
        if self.stack:
            self.stack[-1]["text"].append(data)

    def handle_endtag(self, tag):
        if tag != "a":
            return

        if not self.stack:
            return

        card = self.stack.pop()

        if card["valid"] and card["pic"]:
            self.cards.append(card)


def parse_cards(page):
    parser = CardParser()
    parser.feed(page)
    parser.close()

    result = []
    seen = set()

    for item in parser.cards:
        url = item["url"]

        if not url or url in seen:
            continue

        seen.add(url)

        title = item["title"]

        if not title:
            title = clean(
                " ".join(item["text"])
            )

        if not title:
            slug = urllib.parse.urlsplit(
                url
            ).path.split("/")[-1]

            title = re.sub(
                r"_[a-fA-F0-9]{24}$",
                "",
                slug
            ).replace("-", " ")

        result.append({
            "vod_id": url,
            "vod_name": title[:150],
            "vod_pic": item["pic"],
            "vod_remarks": "",
            "style": dict(LANDSCAPE_STYLE)
        })

    return result


# ============================================================
# Nuxt 数据与播放地址
# ============================================================

def nuxt_strings(page):
    match = re.search(
        r'<script[^>]+id=["\']__NUXT_DATA__["\'][^>]*>'
        r'(.*?)</script>',
        page,
        re.S | re.I
    )

    if not match:
        return []

    try:
        data = json.loads(
            match.group(1)
        )
    except Exception:
        return []

    result = []

    def walk(obj):
        if isinstance(obj, str):
            result.append(obj)

        elif isinstance(obj, list):
            for value in obj:
                walk(value)

        elif isinstance(obj, dict):
            for value in obj.values():
                walk(value)

    walk(data)

    return result


def extract_streams(page):
    found = []
    seen = set()

    for value in nuxt_strings(page):
        value = html.unescape(
            value.replace("\\/", "/")
        )

        if not value.startswith(
            ("http://", "https://")
        ):
            continue

        if not re.search(
            r"\.(?:m3u8|mp4)(?:[?#]|$)",
            value,
            re.I
        ):
            continue

        if "preview" in value.lower():
            continue

        if value in seen:
            continue

        seen.add(value)
        found.append(value)

    def quality_rank(url):
        match = re.search(
            r"(\d{3,4})p(?:[/_.-]|$)",
            urllib.parse.urlsplit(url).path,
            re.I
        )

        if match:
            return (
                0,
                -int(match.group(1))
            )

        if "master.m3u8" in url.lower():
            return (1, 0)

        return (2, 0)

    return sorted(
        found,
        key=quality_rank
    )


def probe_stream(url, timeout=3):
    try:
        if ".m3u8" in url.lower():
            body = request(
                url,
                timeout=timeout,
                max_bytes=120000
            ).decode("utf-8", "replace")

            return "#EXTM3U" in body

        data = request(
            url,
            timeout=timeout,
            headers={
                "Range": "bytes=0-127"
            },
            max_bytes=64
        )

        return bool(data)

    except Exception:
        return False


# ============================================================
# 视频元数据
# ============================================================

def extract_metadata(page, url):
    title = ""

    match = re.search(
        r"<title[^>]*>(.*?)</title>",
        page,
        re.S | re.I
    )

    if match:
        title = clean(match.group(1))

        title = re.sub(
            r"\s*[-|]\s*PMVHaven.*$",
            "",
            title,
            flags=re.I
        )

    creator = ""
    creator_url = ""

    for href, label in re.findall(
        r'<a[^>]+href=["\'](/users/[^"\']+)["\'][^>]*>'
        r'(.*?)</a>',
        page,
        re.S | re.I
    ):
        name = clean(label).replace(
            " Creator",
            ""
        ).strip()

        if name:
            creator = name
            creator_url = absolute(href)
            break

    tags = []
    seen = set()

    for href, label in re.findall(
        r'<a[^>]+href=["\'](/search\?tags=[^"\']+)["\'][^>]*>'
        r'(.*?)</a>',
        page,
        re.S | re.I
    ):
        name = clean(label).lstrip("#").strip()
        target = absolute(href)

        if name and target not in seen:
            seen.add(target)
            tags.append((name, target))

    pic = thumbnail(url)

    for meta in re.findall(
        r"<meta\s+[^>]*>",
        page,
        re.I
    ):
        if "og:image" not in meta:
            continue

        match = re.search(
            r'content=["\']([^"\']+)',
            meta,
            re.I
        )

        if match:
            candidate = absolute(
                match.group(1)
            )

            if "/thumbnails/" in candidate:
                pic = candidate
                break

    return (
        title,
        creator,
        creator_url,
        tags,
        pic
    )


# ============================================================
# 连续播放
# ============================================================

def pack_episodes(items, limit=50):
    result = []
    seen = set()

    for item in items[:limit]:
        url = item.get(
            "vod_id",
            ""
        )

        if not url or url in seen:
            continue

        seen.add(url)

        name = item.get(
            "vod_name",
            "视频"
        )

        name = name.replace("$", " ")
        name = name.replace("#", " ")
        name = name.replace("$$$", " ")

        result.append(
            name[:80] + "$" + url
        )

    return "#".join(result)


# ============================================================
# Spider 主类
# ============================================================

class Spider(BaseSpider):

    def getName(self):
        return "PMVHaven"

    def init(self, extend=""):
        self.last_error = ""

    def destroy(self):
        pass

    def isVideoFormat(self, url):
        return bool(re.search(
            r"\.(m3u8|mp4)(?:[?#]|$)",
            str(url),
            re.I
        ))

    def manualVideoCheck(self):
        return False

    # --------------------------------------------------------
    # FongMi 网络请求
    # --------------------------------------------------------

    def _fetch(self, url, timeout=12):
        url = absolute(url)

        # 优先使用 FongMi 自带网络请求接口。
        try:
            response = self.net.req(
                url,
                {
                    "method": "GET",
                    "timeout": timeout * 1000,
                    "cookie": True,
                    "headers": HEADERS
                }
            )

            if isinstance(response, str):
                response = json.loads(response)

            if isinstance(response, dict):
                code = int(
                    response.get(
                        "code",
                        response.get("status", 0)
                    ) or 0
                )

                content = response.get(
                    "content",
                    ""
                )

                if code == 200 and content:
                    if isinstance(content, bytes):
                        return content.decode(
                            "utf-8",
                            "replace"
                        )

                    return str(content)

        except Exception as error:
            self.last_error = str(error)

        # FongMi 接口不可用时使用 Python 请求。
        try:
            return fetch(
                url,
                timeout=timeout
            )

        except Exception as error:
            self.last_error = str(error)
            return ""

    # --------------------------------------------------------
    # 首页分类
    # --------------------------------------------------------

    def homeContent(self, filter):
        return {
            "class": [
                {
                    "type_id": "/browse",
                    "type_name": "所有视频"
                },
                {
                    "type_id": "/trending",
                    "type_name": "热门视频"
                },
                {
                    "type_id": "/popular",
                    "type_name": "最受欢迎"
                }
            ]
        }

    def homeVideoContent(self):
        page = self._fetch(
            HOST + "/"
        )

        return {
            "list": parse_cards(page)
        }

    # --------------------------------------------------------
    # 分类和作者/标签作品列表
    # --------------------------------------------------------

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = max(
                1,
                int(pg)
            )
        except Exception:
            page = 1

        url = absolute(tid)

        if page > 1:
            separator = (
                "&" if "?" in url else "?"
            )

            url += (
                separator
                + "page="
                + str(page)
            )

        source = self._fetch(url)

        items = parse_cards(source)

        return {
            "list": items,
            "page": page,
            "pagecount": page + 1 if items else page,
            "limit": len(items) or 30,
            "total": 999999 if items else 0
        }

    # --------------------------------------------------------
    # 搜索
    # --------------------------------------------------------

    def searchContent(self, key, quick, pg="1"):
        try:
            page = max(
                1,
                int(pg)
            )
        except Exception:
            page = 1

        key = str(key or "").strip()

        if not key:
            return {
                "list": [],
                "page": 1,
                "pagecount": 1
            }

        if key.startswith("标签:"):
            params = {
                "tags": key[3:],
                "page": page
            }
        else:
            params = {
                "q": key,
                "page": page
            }

        url = (
            HOST
            + "/search?"
            + urllib.parse.urlencode(params)
        )

        source = self._fetch(url)

        items = parse_cards(source)

        return {
            "list": items,
            "page": page,
            "pagecount": page + 1 if items else page,
            "limit": len(items) or 30,
            "total": 999999 if items else 0
        }

    # --------------------------------------------------------
    # 可点击作者和标签
    # --------------------------------------------------------

    def _make_link(self, name, url):
        target = {
            "id": url,
            "name": name,
            "type_flag": 1
        }

        try:
            return self.link(
                name,
                target
            )
        except Exception:
            return name

    # --------------------------------------------------------
    # 视频详情
    # --------------------------------------------------------

    def detailContent(self, ids):
        if not ids:
            return {
                "list": []
            }

        vid = (
            ids[0]
            if isinstance(ids, (list, tuple))
            else str(ids)
        )

        url = canonical(vid)

        if not valid_video(url):
            return {
                "list": []
            }

        source = self._fetch(
            url,
            timeout=12
        )

        if not source:
            return {
                "list": [{
                    "vod_id": url,
                    "vod_name": "详情加载失败",
                    "vod_content": self.last_error
                }]
            }

        (
            title,
            creator,
            creator_url,
            tags,
            pic
        ) = extract_metadata(
            source,
            url
        )

        if not title:
            title = (
                urllib.parse.urlsplit(url)
                .path.split("/")[-1]
                .replace("-", " ")
            )

        # 创作者点击跳转
        creator_text = creator or "未知"

        if creator and creator_url:
            creator_text = self._make_link(
                creator,
                creator_url
            )

        # 标签点击跳转
        tag_links = []

        for name, tag_url in tags:
            tag_links.append(
                self._make_link(
                    name,
                    tag_url
                )
            )

        # 当前视频和相关视频
        current = {
            "vod_id": url,
            "vod_name": title,
            "vod_pic": pic
        }

        related = [
            item
            for item in parse_cards(source)
            if item["vod_id"] != url
        ]

        episodes = pack_episodes(
            [current] + related
        )

        content = (
            "标题：" + title
            + "\n创作者：" + creator_text
            + "\n标签：" + "、".join(tag_links)
        )

        vod = {
            "vod_id": url,
            "vod_name": title,
            "vod_pic": pic,
            "vod_actor": "",
            "vod_director": "",
            "vod_content": content,
            "vod_play_from": "连续播放",
            "vod_play_url": episodes,
            "style": dict(LANDSCAPE_STYLE)
        }

        return {
            "list": [vod]
        }

    # --------------------------------------------------------
    # 播放解析
    # --------------------------------------------------------

    def playerContent(self, flag, id, vipFlags):
        url = canonical(id)

        if not valid_video(url):
            return {
                "parse": 1,
                "url": url
            }

        source = self._fetch(
            url,
            timeout=12
        )

        choices = extract_streams(source)

        if not choices:
            return {
                "parse": 1,
                "url": url
            }

        selected = choices[0]

        # 优先测试 1080P，失败后尝试其他清晰度。
        for candidate in choices[:4]:
            if probe_stream(candidate):
                selected = candidate
                break

        return {
            "parse": 0,
            "url": selected,
            "header": {
                "User-Agent": UA,
                "Referer": HOST + "/",
                "Origin": HOST
            }
        }

    def localProxy(self, param):
        return None
