
# coding: utf-8
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
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": UA,
    "Referer": HOST + "/",
    "Accept-Language": "en-US,en;q=0.9",
}

THUMB = (
    "https://pmvhavencloud.s3.eu-west-par.io.cloud.ovh.net/"
    "thumbnails/{}/thumb_lg.webp"
)


def absolute(url):
    return urllib.parse.urljoin(HOST, html.unescape(url or ""))


def canonical(url):
    p = urllib.parse.urlsplit(absolute(url))
    return urllib.parse.urlunsplit(
        (p.scheme, p.netloc, p.path, "", "")
    )


def request(url, timeout=10, headers=None, max_bytes=3000000):
    h = dict(HEADERS)
    if headers:
        h.update(headers)

    req = urllib.request.Request(
        absolute(url),
        headers=h
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(max_bytes)


def fetch(url, timeout=10):
    return request(url, timeout).decode("utf-8", "replace")


def clean(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(
        r"\s+", " ", html.unescape(value)
    ).strip()


def video_key(url):
    slug = urllib.parse.urlsplit(url).path.rstrip("/").split("/")[-1]
    match = re.search(r"_([a-fA-F0-9]{24})$", slug)
    return match.group(1) if match else ""


def thumbnail(url):
    key = video_key(url)
    return THUMB.format(key) if key else ""


class CardParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = []
        self.current = None
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        href = a.get("href", "")

        if tag == "a" and "/video/" in href:
            if self.current is not None:
                self.finish()

            self.current = {
                "url": absolute(href),
                "title": "",
                "pic": "",
                "text": ""
            }
            self.depth = 1
            return

        if self.current is None:
            return

        if tag == "a":
            self.depth += 1

        if tag == "img":
            sources = [
                a.get("data-src", ""),
                a.get("src", ""),
                a.get("data-original", ""),
            ]

            srcset = a.get("srcset", "")
            if srcset:
                sources.extend(
                    x.strip().split(" ")[0]
                    for x in srcset.split(",")
                )

            for src in sources:
                if "/thumbnails/" in src:
                    self.current["pic"] = absolute(src)
                    if a.get("alt"):
                        self.current["title"] = a["alt"]
                    break

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data + " "

    def handle_endtag(self, tag):
        if self.current is None:
            return

        if tag == "a":
            self.depth -= 1
            if self.depth <= 0:
                self.finish()

    def finish(self):
        if self.current:
            self.cards.append(self.current)
        self.current = None
        self.depth = 0

    def close(self):
        super().close()
        if self.current:
            self.finish()


def parse_cards(page):
    parser = CardParser()
    parser.feed(page)
    parser.close()

    result = []
    seen = set()

    for item in parser.cards:
        url = canonical(item["url"])

        if url in seen:
            continue

        seen.add(url)

        pic = item["pic"]

        if "/thumbnails/" not in pic:
            pic = thumbnail(url)

        title = clean(item["title"])
        if not title:
            title = clean(item["text"])

        if not title:
            title = url.rstrip("/").split("/")[-1].replace("-", " ")

        result.append({
            "vod_id": url,
            "vod_name": title[:150],
            "vod_pic": pic,
            "vod_remarks": ""
        })

    return result


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
        data = json.loads(match.group(1))
    except Exception:
        return []

    values = []

    def walk(obj):
        if isinstance(obj, str):
            values.append(obj)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            for item in obj.values():
                walk(item)

    walk(data)
    return values


def extract_streams(page):
    urls = []
    seen = set()

    for value in nuxt_strings(page):
        value = html.unescape(value)

        if not value.startswith(("https://", "http://")):
            continue

        if not re.search(r"\.(m3u8|mp4)(?:\?|$)", value, re.I):
            continue

        if "preview" in value.lower():
            continue

        if value not in seen:
            seen.add(value)
            urls.append(value)

    def priority(url):
        match = re.search(r"(\d{3,4})p\.m3u8", url, re.I)
        if match:
            return (0, -int(match.group(1)))

        if "master.m3u8" in url:
            return (1, 0)

        return (2, 0)

    return sorted(urls, key=priority)


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
        name = clean(label).replace(" Creator", "").strip()
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

    for tag in re.findall(r"<meta\s+[^>]*>", page, re.I):
        if "og:image" not in tag:
            continue

        match = re.search(
            r'content=["\']([^"\']+)',
            tag,
            re.I
        )

        if match and "/thumbnails/" in match.group(1):
            pic = absolute(match.group(1))
            break

    return title, creator, creator_url, tags, pic


def probe_playlist(url, timeout=3):
    try:
        body = request(
            url,
            timeout=timeout,
            max_bytes=120000
        ).decode("utf-8", "replace")

        return "#EXTM3U" in body
    except Exception:
        return False


def pack_episodes(items, limit=50):
    result = []
    seen = set()

    for item in items[:limit]:
        url = item.get("vod_id", "")

        if not url or url in seen:
            continue

        seen.add(url)

        name = item.get("vod_name", "视频")
        name = name.replace("$", " ")
        name = name.replace("#", " ")
        name = name.replace("$$$", " ")

        result.append(name[:80] + "$" + url)

    return "#".join(result)


class Spider(BaseSpider):

    def getName(self):
        return "PMVHaven"

    def init(self, extend=""):
        pass

    def destroy(self):
        pass

    def isVideoFormat(self, url):
        return bool(re.search(
            r"\.(m3u8|mp4)(?:\?|$)",
            url,
            re.I
        ))

    def manualVideoCheck(self):
        return False

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
        try:
            return {
                "list": parse_cards(fetch(HOST + "/"))
            }
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = max(1, int(pg))
        except Exception:
            page = 1

        url = absolute(tid)

        if page > 1:
            separator = "&" if "?" in url else "?"
            url += separator + "page=" + str(page)

        try:
            items = parse_cards(fetch(url))
        except Exception:
            items = []

        return {
            "list": items,
            "page": page,
            "pagecount": page + 1 if items else page,
            "limit": 30,
            "total": 999999 if items else 0
        }

    def searchContent(self, key, quick, pg="1"):
        try:
            page = max(1, int(pg))
        except Exception:
            page = 1

        key = str(key)

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

        url = HOST + "/search?" + urllib.parse.urlencode(params)

        try:
            items = parse_cards(fetch(url))
        except Exception:
            items = []

        return {
            "list": items,
            "page": page,
            "pagecount": page + 1 if items else page,
            "limit": 30,
            "total": 999999 if items else 0
        }

    def detailContent(self, ids):
        if not ids:
            return {"list": []}

        url = canonical(ids[0])

        try:
            page = fetch(url, timeout=10)
        except Exception:
            return {"list": []}

        title, creator, creator_url, tags, pic = extract_metadata(
            page, url
        )

        if not title:
            title = url.rstrip("/").split("/")[-1].replace("-", " ")

        # 当前视频始终排第一，方便连续播放和客户端预加载。
        current = {
            "vod_id": url,
            "vod_name": title,
            "vod_pic": pic
        }

        related = [
            item for item in parse_cards(page)
            if item["vod_id"] != url
        ]

        sources = ["连续播放"]
        playlists = [pack_episodes([current] + related)]

        # 限制额外请求，避免详情页长时间加载。
        if creator_url:
            try:
                creator_items = parse_cards(
                    fetch(creator_url, timeout=4)
                )
                if creator_items:
                    sources.append("创作者·" + creator[:20])
                    playlists.append(pack_episodes(creator_items))
            except Exception:
                pass

        # 最多加载前两个标签作品列表。
        for label, tag_url in tags[:2]:
            try:
                tag_items = parse_cards(
                    fetch(tag_url, timeout=4)
                )

                if tag_items:
                    sources.append("标签·" + label[:20])
                    playlists.append(pack_episodes(tag_items))
            except Exception:
                pass

        content = (
            "创作者：" + (creator or "未知")
            + "\n标签：" + ", ".join(t[0] for t in tags)
            + "\n可在下方播放源切换创作者或标签作品。"
        )

        vod = {
            "vod_id": url,
            "vod_name": title,
            "vod_pic": pic,
            "vod_actor": creator,
            "vod_director": creator,
            "vod_content": content,
            "vod_play_from": "$$$".join(sources),
            "vod_play_url": "$$$".join(playlists)
        }

        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        url = canonical(id)

        try:
            page = fetch(url, timeout=10)
            choices = extract_streams(page)
        except Exception:
            choices = []

        if not choices:
            return {
                "parse": 1,
                "url": url
            }

        # 1080p 优先，列表不可访问时依次尝试其他清晰度。
        selected = choices[0]

        for candidate in choices[:3]:
            if ".mp4" in candidate.lower():
                selected = candidate
                break

            if probe_playlist(candidate):
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
