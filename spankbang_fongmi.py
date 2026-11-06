# -*- coding: utf-8 -*-
"""
SpankBang Spider for FongMi 5.8.7
Python module Spider (type=3)

Features:
- Home / Trending / Latest / Most popular / PMV (default, new, popular)
- Search and page navigation
- Video detail, tags, creator, related videos
- Playlist carousel entry + playlist page crawling
- Sequential playlist playback
- Runtime stream_data extraction; selectable MP4/HLS qualities
- Landscape cards (16:9)

No third-party Python package is required. HTML parsing uses html.parser.
"""

import re
import json
import html
from urllib.parse import urljoin, quote, urlparse, urlunparse, parse_qsl, urlencode
from html.parser import HTMLParser

from base.spider import Spider as BaseSpider


HOST = "https://zh.spankbang.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0.0.0 Safari/537.36")
PAGE_SIZE = 24
MAX_PLAYLIST_PAGES = 40


class _Node:
    __slots__ = ("tag", "attrs", "children", "parent", "data")

    def __init__(self, tag="", attrs=None, parent=None, data=""):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.children = []
        self.parent = parent
        self.data = data

    def attr(self, key, default=""):
        return self.attrs.get(key.lower(), default) or default

    def classes(self):
        return self.attr("class").split()

    def has_class(self, name):
        return name in self.classes()

    def text(self):
        if self.tag == "#text":
            return self.data
        return "".join(child.text() for child in self.children)

    def walk(self):
        yield self
        for child in self.children:
            if child.tag != "#text":
                for item in child.walk():
                    yield item

    def find_all(self, predicate):
        return [node for node in self.walk() if node is not self and predicate(node)]

    def find(self, predicate):
        for node in self.walk():
            if node is not self and predicate(node):
                return node
        return None


class _TreeParser(HTMLParser):
    VOID = set(("area", "base", "br", "col", "embed", "hr", "img", "input",
                "link", "meta", "param", "source", "track", "wbr"))

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag.lower(), attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag.lower() not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = _Node(tag.lower(), attrs, self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        tag = tag.lower()
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if data:
            self.stack[-1].children.append(_Node("#text", parent=self.stack[-1], data=data))


def _clean(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def _decode_js_string(value):
    return html.unescape(value.replace("\\/", "/").replace("\\u0026", "&"))


class Spider(BaseSpider):

    def init(self, extend=""):
        self.extend = extend or ""
        self.headers = {
            "User-Agent": UA,
            "Referer": HOST + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        }
        self._cache = {}
        self._last_cookie_check = None

    # ------------------------- network / parsing -------------------------

    def _get_cookie(self):
        """读取 FongMi WebView/Spider Cookie；不同客户端版本签名可能不同。"""
        getter = getattr(self.net, "getCookie", None)
        if not callable(getter):
            return ""
        value = None
        for cookie_url in (HOST + "/", HOST):
            try:
                value = getter(cookie_url)
                if value:
                    break
            except TypeError:
                try:
                    value = getter()
                    break
                except Exception:
                    continue
            except Exception:
                continue

        if isinstance(value, dict):
            # 有些实现返回 {name: value}，有些返回 {cookie: "..."}。
            if isinstance(value.get("cookie"), str):
                value = value.get("cookie")
            else:
                value = "; ".join("%s=%s" % (k, v) for k, v in value.items())
        if isinstance(value, (list, tuple)):
            value = "; ".join(str(x) for x in value if x)
        return str(value or "").strip()

    def _has_cf_clearance(self, cookie=None):
        cookie = self._get_cookie() if cookie is None else str(cookie or "")
        return bool(re.search(r"(?:^|;\s*)cf_clearance=", cookie, re.I))

    def _is_cloudflare_challenge(self, content):
        text = (content or "").lower()
        markers = (
            "just a moment...",
            "just a moment",
            "cf-chl-",
            "cf-challenge",
            "challenge-platform",
            "__cf_chl",
            "cf-browser-verification",
            "attention required! | cloudflare",
        )
        return any(marker in text for marker in markers)

    def _request(self, url):
        url = urljoin(HOST + "/", url)
        cached = self._cache.get(url)
        if cached is not None:
            return cached

        request_headers = dict(self.headers)
        cookie = self._get_cookie()
        if cookie:
            request_headers["Cookie"] = cookie

        # cookie=True 让 FongMi 网络层复用 WebView 中完成人机验证后保存的 Cookie。
        result = self.net.req(url, {
            "timeout": 20000,
            "callTimeout": 35000,
            "headers": request_headers,
            "cookie": True,
        })
        if not isinstance(result, dict):
            raise Exception("HTTP 请求返回格式异常")
        code = int(result.get("code", 0) or 0)
        content = result.get("content", "")
        if isinstance(content, bytes):
            content = content.decode("utf-8", "replace")
        if not isinstance(content, str):
            content = str(content)

        if code in (403, 429, 503) or self._is_cloudflare_challenge(content):
            self._cache.pop(url, None)
            if self._has_cf_clearance(cookie):
                raise Exception("SpankBang 仍返回 Cloudflare 验证页（HTTP %s）；当前 cf_clearance 可能已失效或未被目标请求接受" % code)
            raise Exception("SpankBang 需要先完成人机验证：请运行独立的 spankbang_verify Spider，完成验证后重试（HTTP %s）" % code)
        if code < 200 or code >= 400:
            raise Exception("HTTP %s: %s" % (code, url))

        self._cache[url] = content
        return content

    def _tree(self, source):
        parser = _TreeParser()
        parser.feed(source or "")
        parser.close()
        return parser.root

    def _absolute(self, href):
        href = html.unescape((href or "").strip())
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            return ""
        return urljoin(HOST + "/", href)

    def _page_count(self, root):
        nums = []
        for node in root.find_all(lambda n: n.tag == "a" and n.attr("data-page")):
            try:
                nums.append(int(node.attr("data-page")))
            except Exception:
                pass
        if nums:
            return max(nums)
        for node in root.find_all(lambda n: n.tag == "a" and n.parent and
                                  "pagination" in " ".join(n.parent.classes())):
            text = _clean(node.text())
            if text.isdigit():
                nums.append(int(text))
        return max(nums) if nums else 1

    def _page_url(self, base_url, page, root=None):
        if page <= 1:
            return base_url
        if root is not None:
            for node in root.find_all(lambda n: n.tag == "a" and
                                      n.attr("data-page") == str(page) and n.attr("href")):
                return self._absolute(node.attr("href"))

        parsed = urlparse(base_url)
        path = parsed.path or "/"
        if not path.endswith("/"):
            path += "/"
        if re.search(r"/\d+/$", path):
            path = re.sub(r"/\d+/$", "/%d/" % page, path)
        else:
            path += "%d/" % page
        return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params,
                           parsed.query, parsed.fragment))

    def _video_items(self, root, exclude_playlist=False):
        result = []
        seen = set()
        nodes = root.find_all(lambda n: n.attr("data-testid") == "video-item" or
                              (n.has_class("js-video-item") and n.attr("data-id")))
        known_nodes = set(id(node) for node in nodes)
        for anchor in root.find_all(lambda n: n.tag == "a" and
                                    "/video/" in n.attr("href")):
            candidate = anchor
            parent = anchor.parent
            for _ in range(4):
                if parent is None:
                    break
                classes = " ".join(parent.classes()).lower()
                if (re.search(r"(?:video|thumb|item|card)", classes) or
                        parent.attr("data-testid") or parent.attr("data-id")):
                    candidate = parent
                    break
                parent = parent.parent
            if id(candidate) not in known_nodes:
                nodes.append(candidate)
                known_nodes.add(id(candidate))

        for node in nodes:
            if exclude_playlist:
                parent = node.parent
                inside_playlist = False
                while parent is not None:
                    if parent.attr("id") == "playlist_holder":
                        inside_playlist = True
                        break
                    parent = parent.parent
                if inside_playlist:
                    continue
            vid = node.attr("data-id")
            anchors = ([node] if node.tag == "a" else []) + node.find_all(
                lambda n: n.tag == "a" and n.attr("href"))
            href = ""
            for a in anchors:
                h = a.attr("href")
                if "/video/" in h or "/playlist/" in h:
                    href = h
                    break
            if not href and anchors:
                href = anchors[0].attr("href")
            if not href:
                continue

            title = node.attr("title") or node.attr("data-title")
            # The thumbnail anchor usually contains only the HD/duration badge.
            # Prefer a title-bearing text anchor, then the thumbnail's alt text.
            if not title:
                for a in anchors:
                    if a.attr("title"):
                        title = a.attr("title")
                        break
            if not title:
                images = ([node] if node.tag == "img" else []) + node.find_all(
                    lambda n: n.tag == "img")
                for img in images:
                    title = img.attr("alt")
                    if title:
                        break
            if not title:
                for a in anchors:
                    if "/video/" in a.attr("href") and _clean(a.text()):
                        candidate = _clean(a.text())
                        if not re.fullmatch(r"(HD\s*)?\d+\s*[smh]?", candidate, re.I):
                            title = candidate
                            break
            if not title:
                title = node.attr("data-title")
            if not title:
                title = _clean(node.text())
            title = _clean(title)
            if not title:
                continue

            pic = ""
            images = ([node] if node.tag == "img" else []) + node.find_all(
                lambda n: n.tag == "img")
            for img in images:
                pic = img.attr("data-src") or img.attr("src") or img.attr("data-original")
                if pic and "blank.png" not in pic:
                    break
            if pic.startswith("//"):
                pic = "https:" + pic
            elif pic.startswith("/"):
                pic = urljoin(HOST, pic)

            remarks = ""
            for child in node.find_all(lambda n: n.attr("data-testid") in
                                       ("video-item-length", "video-item-resolution")):
                value = _clean(child.text())
                if value:
                    remarks = (remarks + " " + value).strip()

            key = vid or href
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "id": vid or self._id_from_href(href),
                "href": self._absolute(href),
                "name": title,
                "pic": pic,
                "remarks": remarks,
            })
        return result

    def _id_from_href(self, href):
        path = urlparse(href).path
        return path.strip("/") or href

    def _card(self, item):
        return {
            "vod_id": "sbvideo:" + quote(str(item.get("href") or item.get("id") or ""), safe=""),
            "vod_name": item.get("name") or "SpankBang 视频",
            "vod_pic": item.get("pic") or "",
            "vod_remarks": item.get("remarks") or "",
            "ratio": 1.78,
        }

    def _error_card(self, error):
        return {
            "vod_id": "sb-error",
            "vod_name": "SpankBang 加载失败",
            "vod_pic": "",
            "vod_remarks": _clean(error)[:180],
        }

    def _empty_page_card(self, root):
        titles = root.find_all(lambda n: n.tag == "title")
        title = _clean(titles[0].text()) if titles else "无页面标题"
        video_links = len(root.find_all(
            lambda n: n.tag == "a" and "/video/" in n.attr("href")))
        return self._error_card(
            "页面已加载但未识别到视频卡片；标题=%s；视频链接=%d"
            % (title, video_links)
        )

    def _list_page(self, url):
        source = self._request(url)
        root = self._tree(source)
        return root, self._video_items(root), self._page_count(root)

    def _all_playlist_items(self, playlist_url, first_root=None):
        all_items = []
        seen = set()
        root = first_root
        page_count = 1

        for page in range(1, MAX_PLAYLIST_PAGES + 1):
            if page == 1 and root is not None:
                current_root = root
            else:
                page_url = self._page_url(playlist_url, page, root)
                if page > 1 and page_count and page > page_count:
                    break
                try:
                    source = self._request(page_url)
                    current_root = self._tree(source)
                except Exception:
                    break

            if page == 1:
                page_count = self._page_count(current_root)
            items = self._video_items(current_root)
            added = 0
            for item in items:
                key = item.get("id") or item.get("href")
                if key and key not in seen:
                    seen.add(key)
                    all_items.append(item)
                    added += 1

            if page >= page_count or not items or added == 0:
                break
            root = current_root

        return all_items

    # ------------------------------ home --------------------------------

    def homeContent(self, filter):
        classes = [
            {"type_id": "/", "type_name": "首页", "ratio": 1.78},
            {"type_id": "/trending_videos/", "type_name": "趋势", "ratio": 1.78},
            {"type_id": "/new_videos/", "type_name": "最新", "ratio": 1.78},
            {"type_id": "/most_popular/", "type_name": "最受欢迎", "ratio": 1.78},
            {"type_id": "/s/pmv/", "type_name": "PMV 默认", "ratio": 1.78},
            {"type_id": "/s/pmv/?o=new", "type_name": "PMV 最新", "ratio": 1.78},
            {"type_id": "/s/pmv/?o=popular", "type_name": "PMV 最受欢迎", "ratio": 1.78},
        ]
        return {"class": classes}

    def homeVideoContent(self):
        try:
            root, items, pagecount = self._list_page(HOST + "/")
            return {"list": [self._card(x) for x in items]}
        except Exception as e:
            return {"list": [self._error_card(e)]}

    # ------------------------------ lists -------------------------------

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = max(1, int(pg or "1"))
        except Exception:
            page = 1

        base = str(tid or "/")
        if base.startswith("sbvideo:"):
            base = "/"
        if not base.startswith("http"):
            base = urljoin(HOST + "/", base.lstrip("/"))
        try:
            root, items, pagecount = self._list_page(base)
            if page > 1:
                page_url = self._page_url(base, page, root)
                root, items, pagecount = self._list_page(page_url)
            if not items:
                return {
                    "list": [self._empty_page_card(root)],
                    "page": page,
                    "pagecount": pagecount,
                }
            return {
                "list": [self._card(x) for x in items],
                "page": page,
                "pagecount": pagecount,
            }
        except Exception as e:
            return {
                "list": [self._error_card(e)],
                "page": page,
                "pagecount": 0,
            }

    def searchContent(self, key, quick, pg="1"):
        keyword = _clean(key)
        try:
            page = max(1, int(pg or "1"))
        except Exception:
            page = 1
        search_url = HOST + "/s/" + quote(keyword, safe="") + "/"
        try:
            root, items, pagecount = self._list_page(search_url)
            if page > 1:
                page_url = self._page_url(search_url, page, root)
                root, items, pagecount = self._list_page(page_url)
            return {
                "list": [self._card(x) for x in items],
                "page": page,
                "pagecount": pagecount,
            }
        except Exception as e:
            return {
                "list": [self._error_card(e)],
                "page": page,
                "pagecount": 0,
            }

    # ------------------------------ detail ------------------------------

    def _links_in(self, root, predicate):
        values = []
        seen = set()
        if root is None:
            return values
        for a in root.find_all(lambda n: n.tag == "a" and n.attr("href")):
            href = a.attr("href")
            name = _clean(a.text())
            if not name or not predicate(href):
                continue
            key = (href, name.lower())
            if key in seen:
                continue
            seen.add(key)
            values.append((name, href))
        return values

    def _link(self, name, href):
        target = {
            "id": href,
            "name": name,
            "type_flag": "1",
        }
        try:
            return self.link(name, target)
        except Exception:
            return name

    def _extract_streams(self, source):
        match = re.search(r"\bvar\s+stream_data\s*=\s*(\{.*?\})\s*;", source, re.S)
        if not match:
            return []
        block = match.group(1)
        choices = []
        order = ("4k", "1080p", "720p", "480p", "320p", "240p")
        for quality in order:
            urls = []
            for key in (quality, "m3u8_" + quality):
                m = re.search(r"""['"]%s['"]\s*:\s*\[\s*['"]([^'"]+)""" %
                              re.escape(key), block, re.I)
                if m:
                    url = _decode_js_string(m.group(1))
                    if url.startswith("//"):
                        url = "https:" + url
                    if url.startswith("http") and url not in urls:
                        urls.append(url)
            for url in urls:
                label = quality.upper()
                if ".m3u8" in url:
                    label += " HLS"
                elif label == "4K":
                    label += " MP4"
                choices.append((label, url))

        if not choices:
            m = re.search(r"""['"]main['"]\s*:\s*\[\s*['"]([^'"]+)""", block, re.I)
            if m:
                url = _decode_js_string(m.group(1))
                if url.startswith("//"):
                    url = "https:" + url
                if url.startswith("http"):
                    choices.append(("默认画质", url))
        # 去重，同时保留高画质优先顺序
        unique = []
        seen = set()
        for name, url in choices:
            if url not in seen:
                seen.add(url)
                unique.append((name, url))
        return unique

    def _playlist_info(self, root):
        holder = root.find(lambda n: n.attr("id") == "playlist_holder")
        if holder is None:
            return None, "", 0, []
        anchor = holder.find(lambda n: n.tag == "a" and "/playlist/" in n.attr("href"))
        if anchor is None:
            return None, "", 0, []
        name = _clean(anchor.text())
        url = self._absolute(anchor.attr("href"))
        count = 0
        em = holder.find(lambda n: n.tag == "em")
        if em:
            m = re.search(r"(\d+)", _clean(em.text()))
            if m:
                count = int(m.group(1))
        preview = self._video_items(holder)
        return name, url, count, preview

    def _detail_vod(self, video_url):
        source = self._request(video_url)
        root = self._tree(source)

        title_node = root.find(lambda n: n.attr("data-testid") == "video-title")
        title = _clean(title_node.text()) if title_node else ""
        if not title:
            title_node = root.find(lambda n: n.tag == "h1")
            title = _clean(title_node.text()) if title_node else ""
        if not title:
            m = re.search(r"<title[^>]*>(.*?)</title>", source, re.I | re.S)
            title = _clean(m.group(1)) if m else "SpankBang 视频"

        pic = ""
        og = root.find(lambda n: n.tag == "meta" and n.attr("property") == "og:image")
        if og:
            pic = og.attr("content")
        if not pic:
            img = root.find(lambda n: n.tag == "img" and n.attr("id") == "player_cover_img")
            if img:
                pic = img.attr("src") or img.attr("data-src")

        # 标签、作者频道、演员链接均从视频标签横向滚动区提取。
        tag_box = root.find(lambda n: n.attr("data-testid") == "video-tags")
        tags = self._links_in(tag_box, lambda h: h.startswith("/s/") or
                              "/channel/" in h or "/pornstar/" in h)
        actor_links = []
        tag_names = []
        for name, href in tags:
            if "/channel/" in href or "/pornstar/" in href:
                actor_links.append(self._link(name, href))
            elif href.startswith("/s/"):
                tag_names.append(self._link(name, href))

        # 标签区可能没有频道链接时，回退到页面中可识别的频道链接。
        if not actor_links:
            for name, href in self._links_in(root, lambda h: "/channel/" in h):
                actor_links.append(self._link(name, href))
                break

        # 详情页播放列表模块：提取 playlist_holder 的链接、名称、数量和预览项。
        playlist_name, playlist_url, playlist_count, playlist_preview = self._playlist_info(root)

        # 详情页 stream_data 是运行时签名地址，不能把上传 HTML 中的旧地址写死。
        qualities = self._extract_streams(source)
        play_groups = []
        if qualities:
            play_groups.append(("SpankBang", [("播放", "sbplay:" + quote(video_url, safe=""))]))

        # 播放列表页实际内容由 playlist URL 取得；横向滚动预览只作无分页的回退。
        playlist_items = []
        if playlist_url:
            playlist_items = self._all_playlist_items(playlist_url)
            if not playlist_items:
                playlist_items = playlist_preview
            if playlist_items:
                episodes = []
                for index, item in enumerate(playlist_items, 1):
                    target = item.get("href") or video_url
                    epid = "sbplay:" + quote(target, safe="")
                    epname = item.get("name") or ("第 %d 个视频" % index)
                    epname = epname[:100]
                    episodes.append(epname.replace("#", "＃").replace("$", "＄") + "$" + epid)
                play_groups.append((("播放列表 - " + playlist_name), episodes))

        # 相关视频作为独立分组，点击后仍进入对应视频详情/播放地址。
        related = []
        for item in self._video_items(root, exclude_playlist=True):
            if item.get("href") and item.get("href") != video_url:
                related.append(item)
        if related:
            eps = []
            for index, item in enumerate(related, 1):
                target = item.get("href")
                rel_name = (item.get("name") or ("相关视频 %d" % index))[:100]
                eps.append(rel_name.replace("#", "＃").replace("$", "＄")
                           + "$sbplay:" + quote(target, safe=""))
            play_groups.append(("相关推荐", eps))

        vod_play_from = "$$$".join(group[0] for group in play_groups)
        vod_play_url = "$$$".join("#".join(group[1]) for group in play_groups)

        desc_parts = []
        if playlist_name:
            desc_parts.append("播放列表：%s（%d 视频）" % (playlist_name, playlist_count))
        if tag_names:
            desc_parts.append("标签：" + "、".join(tag_names))
        desc_parts.append("来源：SpankBang")

        vod = {
            "vod_id": "sbvideo:" + quote(video_url, safe=""),
            "vod_name": title,
            "vod_pic": pic,
            "vod_remarks": "",
            "vod_actor": "、".join(actor_links + tag_names),
            "vod_director": self._link(playlist_name, urlparse(playlist_url).path)
                            if playlist_name and playlist_url else "",
            "vod_content": "\n".join(desc_parts),
            "vod_play_from": vod_play_from,
            "vod_play_url": vod_play_url,
            "ratio": 1.78,
        }
        return vod

    def detailContent(self, ids):
        result = []
        for raw_id in ids or []:
            value = str(raw_id or "")
            if value.startswith("sbvideo:"):
                encoded = value[len("sbvideo:"):]
                try:
                    video_url = __import__("urllib.parse", fromlist=["unquote"]).unquote(encoded)
                except Exception:
                    video_url = encoded
            else:
                video_url = value
            if not video_url.startswith("http"):
                video_url = urljoin(HOST + "/", video_url.lstrip("/"))
            try:
                result.append(self._detail_vod(video_url))
            except Exception:
                result.append({
                    "vod_id": value,
                    "vod_name": "视频详情获取失败",
                    "vod_pic": "",
                    "vod_content": "无法读取该视频详情页，请稍后重试。",
                })
        return {"list": result}

    # ------------------------------ player ------------------------------

    def playerContent(self, flag, id, vipFlags):
        value = str(id or "")
        if value.startswith("sbplay:"):
            encoded = value[len("sbplay:"):]
            try:
                video_url = __import__("urllib.parse", fromlist=["unquote"]).unquote(encoded)
            except Exception:
                video_url = encoded
        elif value.startswith("sbvideo:"):
            encoded = value[len("sbvideo:"):]
            try:
                video_url = __import__("urllib.parse", fromlist=["unquote"]).unquote(encoded)
            except Exception:
                video_url = encoded
        else:
            video_url = value

        if not video_url.startswith("http"):
            video_url = urljoin(HOST + "/", video_url.lstrip("/"))

        source = self._request(video_url)
        choices = self._extract_streams(source)
        if not choices:
            return {"parse": 1, "url": video_url, "header": dict(self.headers)}

        # FongMi 5.8.7：多画质 URL 必须按「名称、URL」成对返回。
        urls = []
        for name, url in choices:
            urls.extend([name, url])
        return {
            "parse": 0,
            "url": urls,
            "header": {
                "User-Agent": self.headers["User-Agent"],
                "Referer": video_url,
                **({"Cookie": self._get_cookie()} if self._get_cookie() else {}),
            },
            "artwork": self._cover_from_html(source),
        }

    def _cover_from_html(self, source):
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
                      source, re.I)
        return html.unescape(m.group(1)) if m else ""

    # ------------------------------- action ------------------------------

    def action(self, action):
        return {}

    def destroy(self):
        self._cache = {}
