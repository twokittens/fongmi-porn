# -*- coding: utf-8 -*-
"""
黄果短剧 FongMi Python Spider

基于原版 huangguo_fongmi(2).py 修改。

功能：
1. 分类、排行榜、详情、搜索：优先请求 JSON API，失败后回退 HTML。
2. 播放：使用 dx150-edge-v1 加密协议直接请求源站。
3. 封面：AES-CBC 解密，保留 FongMi 本地代理。
4. 保留 FongMi Spider 原有接口。

注意：
加密播放需要 cryptography 库。
"""

import re
import json
import base64
import binascii
import hashlib
import html as html_lib
import time

from urllib.parse import urljoin, quote, urlencode

from base.spider import Spider as BaseSpider


# ============================================================
# 基础配置
# ============================================================

SITE = "https://huangguoai.com"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": UA,
    "Referer": SITE + "/",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "application/json, text/plain, */*"
}

IMG_KEY = b"f5d965df75336270"
IMG_IV = b"97b60394abc2fbe1"

DX_PROTOCOL = "dx150-edge-v1"

CLASSES = [
    {"type_id": "ai-duanju", "type_name": "AI成人短剧"},
    {"type_id": "ai-manju", "type_name": "AI成人漫剧"},
    {"type_id": "ai-huanlian", "type_name": "AI换脸"},
    {"type_id": "ai-mogai", "type_name": "AI魔改"},
    {"type_id": "ranks/hot", "type_name": "排行榜"},
]


# ============================================================
# 通用工具
# ============================================================

def match(pattern, text, flags=re.I | re.S):
    m = re.search(pattern, text or "", flags)
    return m.group(1) if m else ""


def clean(value):
    value = re.sub(
        r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>",
        "",
        value or "",
        flags=re.I | re.S
    )
    value = re.sub(r"<[^>]+>", "", value)
    return html_lib.unescape(value).strip()


def fix(url):
    return urljoin(
        SITE + "/",
        html_lib.unescape(str(url or ""))
    )


def cover(url):
    url = fix(url) if url else ""

    if not url.startswith(("http://", "https://")):
        return ""

    return url


def b64url_encode(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(value):
    value = str(value or "")
    value += "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value.encode("ascii"))


def json_load(value, default=None):
    if default is None:
        default = {}

    if isinstance(value, dict):
        return value

    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")

    try:
        return json.loads(value)
    except Exception:
        return default


# ============================================================
# 图片处理
# ============================================================

def decrypt_image(raw):

    def mime_of(data):
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"

        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"

        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return "image/webp"

        if data.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"

        return ""

    if isinstance(raw, (bytes, bytearray)):
        payload = bytes(raw)

        if not mime_of(payload):
            if re.fullmatch(rb"[A-Za-z0-9+/=\r\n]+", payload):
                try:
                    payload = base64.b64decode(payload)
                except Exception:
                    pass

    elif isinstance(raw, str):
        value = raw.strip()

        if value.startswith("data:") and "," in value:
            value = value.split(",", 1)[1]

        try:
            payload = base64.b64decode(value, validate=True)
        except Exception:
            return None

    else:
        return None

    mime = mime_of(payload)

    if mime:
        return mime, base64.b64encode(payload).decode("ascii")

    if not payload:
        return None

    original_length = len(payload)

    padded = payload + bytes((-original_length) % 16)

    decrypted = None

    try:
        from Crypto.Cipher import AES

        decrypted = AES.new(
            IMG_KEY,
            AES.MODE_CBC,
            IMG_IV
        ).decrypt(padded)

    except ImportError:

        try:
            from Cryptodome.Cipher import AES

            decrypted = AES.new(
                IMG_KEY,
                AES.MODE_CBC,
                IMG_IV
            ).decrypt(padded)

        except ImportError:

            try:
                from cryptography.hazmat.primitives.ciphers import (
                    Cipher,
                    algorithms,
                    modes
                )

                dec = Cipher(
                    algorithms.AES(IMG_KEY),
                    modes.CBC(IMG_IV)
                ).decryptor()

                decrypted = dec.update(padded) + dec.finalize()

            except ImportError:
                print("[HG-COVER] AES library unavailable")
                return None

    if not decrypted:
        return None

    decrypted = decrypted[:original_length]

    mime = mime_of(decrypted)

    if not mime:
        print("[HG-COVER] image decrypt failed")
        return None

    return mime, base64.b64encode(decrypted).decode("ascii")


# ============================================================
# HTTP 请求
# ============================================================

def request(spider, url, method="GET", data=None, referer=None,
            buffer=None, timeout=25000):

    headers = dict(HEADERS)

    if referer:
        headers["Referer"] = referer

    options = {
        "method": method.upper(),
        "timeout": timeout,
        "headers": headers,
        "cookie": True
    }

    if data is not None:
        options["data"] = (
            data if isinstance(data, str)
            else json.dumps(data, ensure_ascii=False)
        )
        headers["Content-Type"] = "application/json"

    if buffer is not None:
        options["buffer"] = buffer

    try:
        response = spider.net.req(url, options)

        if isinstance(response, str):
            response = json.loads(response)

        if not isinstance(response, dict):
            print("[Huangguo] invalid response:", type(response).__name__)
            return None

        return response

    except Exception as exc:
        print("[Huangguo] request error:", url, repr(exc))
        return None


def fetch(spider, url, referer=None):

    response = request(
        spider,
        url,
        method="GET",
        referer=referer
    )

    if not response:
        return ""

    status = response.get("code", response.get("status", 0))

    try:
        status = int(status)
    except Exception:
        status = 0

    if status != 200:
        print("[Huangguo] HTTP", status, url)
        return ""

    content = response.get("content", "") or ""

    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")

    return str(content)


def fetch_json(spider, url, referer=None):

    content = fetch(spider, url, referer)

    if not content:
        return {}

    return json_load(content, {})


# ============================================================
# HTML 解析
# ============================================================

def blocks(text, marker):

    starts = [
        m.end()
        for m in re.finditer(
            r'<div\b[^>]*class=["\'][^"\']*\b'
            + re.escape(marker)
            + r'\b[^"\']*["\'][^>]*>',
            text or "",
            re.I
        )
    ]

    return [
        text[
            starts[i]:
            starts[i + 1] if i + 1 < len(starts)
            else len(text)
        ]
        for i in range(len(starts))
    ]


def image_from_card(fragment):

    tag = match(r"<img\b([^>]+)>", fragment)

    if not tag:
        return ""

    for attribute in (
        "data-src",
        "data-original",
        "data-lazy-src",
        "src"
    ):

        m = re.search(
            r"(?<![\w-])"
            + re.escape(attribute)
            + r"\s*=\s*([\"'])(.*?)\1",
            tag,
            re.I | re.S
        )

        if not m:
            continue

        url = html_lib.unescape(m.group(2)).strip()

        if not url:
            continue

        if url.startswith(("data:", "blob:")):
            continue

        if "cover-placeholder" in url:
            continue

        return cover(url)

    return ""


def parse_cards(page, all_grids=False):

    grids = blocks(page, "hg-card-grid")

    scopes = grids if all_grids else grids[:1]

    if not scopes:
        scopes = [page]

    result = []
    seen = set()

    for scope in scopes:

        for item in blocks(scope, "hg-drama-card"):

            vid = match(
                r'href=["\'][^"\']*/(?:detail|video)/(\d+)/',
                item
            )

            if not vid or vid in seen:
                continue

            title = clean(
                match(
                    r'hg-drama-card__title[^>]*>(.*?)</a>',
                    item
                )
            )

            if not title:
                title = clean(
                    match(
                        r'<a\b[^>]*href=["\'][^"\']*/'
                        r'(?:detail|video)/\d+/[^>]*>(.*?)</a>',
                        item
                    )
                )

            if not title:
                continue

            pic = image_from_card(item)

            episode = clean(
                match(
                    r'hg-drama-card__episode[^>]*>(.*?)</span>',
                    item
                )
            )

            score = clean(
                match(
                    r'hg-drama-card__score[^>]*>(.*?)</span>',
                    item
                )
            )

            count_match = re.search(r"(\d+)", episode)

            episode_count = (
                int(count_match.group(1))
                if count_match else 0
            )

            seen.add(vid)

            result.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": " · ".join(
                    x for x in (episode, score) if x
                ),
                "_episode_count": episode_count
            })

    if not result:

        for m in re.finditer(
            r'<a\b[^>]*href=["\']([^"\']*/video/(\d+)/)'
            r'[^"\']*["\'][^>]*>(.*?)</a>',
            page or "",
            re.I | re.S
        ):

            vid = m.group(2)

            title = clean(m.group(3))
            title = re.sub(r"全集在线观看$", "", title).strip()

            if vid in seen or not title or title.isdigit():
                continue

            seen.add(vid)

            result.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": "",
                "vod_remarks": ""
            })

    return result


def parse_ranks(page):

    rank = (
        match(
            r'(<div\b[^>]*class=["\'][^"\']*hg-rank-list'
            r'[^"\']*["\'][^>]*>.*)',
            page
        )
        or page
    )

    result = []
    seen = set()

    for item in blocks(rank, "hg-rank-item"):

        vid = match(
            r'href=["\'][^"\']*/(?:detail|video)/(\d+)/',
            item
        )

        if not vid or vid in seen:
            continue

        title = clean(
            match(
                r'hg-rank-item__title[^>]*>(.*?)</h2>',
                item
            )
        )

        if not title:
            title = clean(
                match(
                    r'<a\b[^>]*href=["\'][^"\']*/'
                    r'(?:detail|video)/\d+/[^>]*>(.*?)</a>',
                    item
                )
            )

        if not title:
            continue

        seen.add(vid)

        result.append({
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": image_from_card(item),
            "vod_remarks": clean(
                match(
                    r'hg-rank-item__tags[^>]*>(.*?)</div>',
                    item
                )
            )
        })

        if len(result) >= 20:
            break

    return result


def initial_data(page):

    raw = match(
        r'<script\b[^>]*id=["\']videoInitialData["\']'
        r'[^>]*>(.*?)</script>',
        page
    )

    return json_load(raw, {})


def episodes(page, vid):

    result = {}

    pattern = (
        r'<a\b[^>]*href=["\']([^"\']*/(?:video|detail)/'
        + re.escape(vid)
        + r'/[^"\']*)["\'][^>]*>.*?</a>'
    )

    for m in re.finditer(pattern, page, re.I | re.S):

        tag = m.group(0)
        url = fix(m.group(1))

        ep = (
            match(r'data-ep-id=["\'](\d+)', tag)
            or match(r"/ep-(\d+)/?", url)
        )

        if not ep:
            ep = match(r"(\d+)", clean(tag))

        ep = str(int(ep)) if ep else "1"

        result.setdefault(ep, url)

    for m in re.finditer(
        r'href=["\']([^"\']*/video/'
        + re.escape(vid)
        + r'/(?:ep-(\d+)/)?)',
        page,
        re.I
    ):

        result.setdefault(
            m.group(2) or "1",
            fix(m.group(1))
        )

    if not result:
        result["1"] = SITE + "/video/" + vid + "/"

    return sorted(
        result.items(),
        key=lambda pair: int(pair[0])
    )


# ============================================================
# JSON API
# ============================================================

def api_items(data):

    if not isinstance(data, dict):
        return []

    payload = data.get("data", data)

    if isinstance(payload, list):
        raw_items = payload

    elif isinstance(payload, dict):
        raw_items = (
            payload.get("items")
            or payload.get("list")
            or payload.get("videos")
            or []
        )

    else:
        raw_items = []

    result = []
    seen = set()

    for item in raw_items:

        if not isinstance(item, dict):
            continue

        vid = str(
            item.get("id")
            or item.get("video_id")
            or ""
        )

        title = clean(
            str(
                item.get("title")
                or item.get("name")
                or ""
            )
        )

        if not vid.isdigit() or not title or vid in seen:
            continue

        pic = (
            item.get("cover")
            or item.get("cover_src")
            or item.get("coverSrc")
            or item.get("image")
            or item.get("thumbnail")
            or ""
        )

        count = (
            item.get("episode_count")
            or item.get("total_episodes")
            or item.get("episodes_count")
            or 0
        )

        score = item.get("score") or ""

        remarks = ""

        if count:
            remarks = "更新至%s集" % count

        if score:
            remarks = " · ".join(
                x for x in (remarks, str(score) + "分") if x
            )

        result.append({
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": cover(pic),
            "vod_remarks": remarks
        })

        seen.add(vid)

    return result


def api_category(spider, tid, page, sort=""):

    path = quote(str(tid), safe="")

    params = {
        "page": page,
        "size": 21
    }

    if sort:
        params["sort"] = sort

    url = (
        SITE
        + "/api/videos/category/"
        + path
        + "?"
        + urlencode(params)
    )

    data = fetch_json(spider, url)

    items = api_items(data)

    payload = data.get("data", data)

    if not isinstance(payload, dict):
        payload = {}

    try:
        total = int(
            payload.get("total")
            or payload.get("total_count")
            or payload.get("totalItems")
            or 0
        )
    except Exception:
        total = 0

    try:
        pages = int(
            payload.get("pages")
            or payload.get("total_pages")
            or 0
        )
    except Exception:
        pages = 0

    if not pages and total:
        pages = (total + 20) // 21

    return items, pages, total


def api_search(spider, keyword, page):

    params = {
        "keyword": keyword,
        "page": page
    }

    url = SITE + "/api/search?" + urlencode(params)

    data = fetch_json(spider, url)

    return api_items(data)


def api_detail(spider, vid):

    url = SITE + "/api/videos/" + str(vid)

    data = fetch_json(spider, url)

    payload = data.get("data", data)

    if not isinstance(payload, dict):
        return {}

    return payload


# ============================================================
# dx150-edge-v1 加密播放协议
# ============================================================

class DXCrypto:

    def __init__(self, spider):
        self.spider = spider
        self.session = None

    def _import_crypto(self):

        try:
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.kdf.hkdf import HKDF
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            return ec, hashes, serialization, HKDF, AESGCM

        except ImportError as exc:
            raise RuntimeError(
                "缺少 cryptography 库，无法执行 dx150-edge-v1 播放解密"
            ) from exc

    def _nonce(self, seq):

        nonce = bytearray(12)

        nonce[8:12] = int(seq).to_bytes(
            4,
            byteorder="big"
        )

        return bytes(nonce)

    def _derive_key(
        self,
        secret,
        salt,
        info,
        HKDF,
        hashes
    ):

        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=info
        ).derive(secret)

    def open(self):

        ec, hashes, serialization, HKDF, AESGCM = (
            self._import_crypto()
        )

        private_key = ec.generate_private_key(
            ec.SECP256R1()
        )

        public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )

        hello_url = SITE + "/api/playback/request"

        hello_body = {
            "v": 1,
            "type": "hello",
            "client_pub": b64url_encode(public_key)
        }

        response = request(
            self.spider,
            hello_url,
            method="POST",
            data=hello_body,
            referer=SITE + "/"
        )

        if not response:
            raise RuntimeError("播放握手请求失败")

        status = response.get("code", response.get("status", 0))

        if str(status) != "200":
            raise RuntimeError(
                "播放握手 HTTP 状态异常: " + str(status)
            )

        hello = json_load(response.get("content", ""), {})

        if not isinstance(hello, dict):
            raise RuntimeError("播放握手响应格式错误")

        server_pub = hello.get("server_pub")
        salt_value = hello.get("salt")
        kid = hello.get("kid")
        sid = hello.get("sid")

        if not all((server_pub, salt_value, kid, sid)):
            raise RuntimeError("播放握手缺少必要字段")

        server_public_bytes = b64url_decode(server_pub)

        server_public_key = (
            ec.EllipticCurvePublicKey.from_encoded_point(
                ec.SECP256R1(),
                server_public_bytes
            )
        )

        shared_secret = private_key.exchange(
            ec.ECDH(),
            server_public_key
        )

        salt = b64url_decode(salt_value)

        site_value = str(hello.get("site") or SITE)

        info = "\n".join([
            DX_PROTOCOL,
            "playback",
            site_value,
            str(kid),
            str(sid)
        ])

        req_key = self._derive_key(
            shared_secret,
            salt,
            (info + "\nreq").encode("utf-8"),
            HKDF,
            hashes
        )

        res_key = self._derive_key(
            shared_secret,
            salt,
            (info + "\nres").encode("utf-8"),
            HKDF,
            hashes
        )

        self.session = {
            "AESGCM": AESGCM,
            "req_key": req_key,
            "res_key": res_key,
            "kid": str(kid),
            "sid": str(sid),
            "info": info,
            "seq": 0,
            "time_offset": (
                int(hello.get("server_time") or time.time())
                - int(time.time())
            )
        }

        return True

    def packet(self, method, path, body=None):

        if body is None:
            body_bytes = b""
            content_type = ""

        else:
            body_bytes = json.dumps(
                body,
                ensure_ascii=False,
                separators=(",", ":")
            ).encode("utf-8")

            content_type = "application/json"

        return {
            "method": method.upper(),
            "path": path,
            "body": base64.b64encode(
                body_bytes
            ).decode("ascii"),
            "content_type": content_type,
            "visitor_id": ""
        }

    def call(self, packet):

        if not self.session:
            self.open()

        s = self.session

        s["seq"] += 1

        seq = s["seq"]

        ts = int(time.time()) + s["time_offset"]

        aad = "\n".join([
            s["info"],
            "req",
            str(seq),
            str(ts)
        ]).encode("utf-8")

        plaintext = json.dumps(
            {"request": packet},
            ensure_ascii=False,
            separators=(",", ":")
        ).encode("utf-8")

        AESGCM = s["AESGCM"]

        ciphertext = AESGCM(
            s["req_key"]
        ).encrypt(
            self._nonce(seq),
            plaintext,
            aad
        )

        envelope = {
            "v": 1,
            "type": "call",
            "kid": s["kid"],
            "sid": s["sid"],
            "seq": seq,
            "ts": ts,
            "ciphertext": base64.b64encode(
                ciphertext
            ).decode("ascii")
        }

        response = request(
            self.spider,
            SITE + "/api/playback/request",
            method="POST",
            data=envelope,
            referer=SITE + "/"
        )

        if not response:
            raise RuntimeError("播放加密请求失败")

        status = response.get("code", response.get("status", 0))

        if str(status) != "200":
            raise RuntimeError(
                "播放请求 HTTP 状态异常: " + str(status)
            )

        outer = json_load(response.get("content", ""), {})

        encrypted = outer.get("ciphertext")

        if not encrypted:
            raise RuntimeError("播放响应缺少 ciphertext")

        response_seq = int(outer.get("seq") or seq)
        response_ts = int(outer.get("ts") or ts)

        response_aad = "\n".join([
            s["info"],
            "res",
            str(response_seq),
            str(response_ts)
        ]).encode("utf-8")

        encrypted_bytes = base64.b64decode(encrypted)

        decrypted = AESGCM(
            s["res_key"]
        ).decrypt(
            self._nonce(response_seq),
            encrypted_bytes,
            response_aad
        )

        result = json.loads(
            decrypted.decode("utf-8")
        )

        inner = result.get("body", result)

        if isinstance(inner, str):
            inner = json_load(inner, {})

        if not isinstance(inner, dict):
            raise RuntimeError("播放响应解密后格式错误")

        return inner


# ============================================================
# 播放地址获取
# ============================================================

def encrypted_play(spider, vid, ep):

    try:

        crypto = DXCrypto(spider)

        packet = crypto.packet(
            "POST",
            "/api/videos/%s/episodes/%s/playback" % (
                vid,
                ep
            ),
            {}
        )

        result = crypto.call(packet)

        data = result.get("data", result)

        if not isinstance(data, dict):
            return ""

        streams = data.get("streams") or {}

        if not isinstance(streams, dict):
            streams = {}

        url = (
            streams.get("main")
            or streams.get("preview")
            or ""
        )

        if isinstance(url, dict):
            url = url.get("url") or url.get("src") or ""

        if not url:
            hevc = streams.get("hevc")

            if isinstance(hevc, dict):
                url = hevc.get("url") or hevc.get("src") or ""
            elif isinstance(hevc, str):
                url = hevc

        if isinstance(url, str) and url.startswith(
            ("http://", "https://")
        ):
            return url

        return ""

    except Exception as exc:
        print("[Huangguo] encrypted playback failed:", repr(exc))
        return ""


def extract_play(page, ep):

    data = initial_data(page)

    srcs = data.get("epPlaySrcs") or {}

    url = (
        srcs.get(str(ep))
        or data.get("videoSrc")
        or ""
    )

    if not isinstance(url, str):
        url = ""

    url = (
        url.replace("\\u0026", "&")
        .replace("\\/", "/")
    )

    if not url:
        url = match(
            r'(https?:\\?/\\?/[^"\'<>\s]+?\.m3u8'
            r'(?:\?[^"\'<>\s]*)?)',
            page
        )

    url = fix(url) if url else ""

    if url.startswith(("http://", "https://")):
        return url

    return ""


# ============================================================
# FongMi Spider
# ============================================================

class Spider(BaseSpider):

    def __init__(self):

        super().__init__()

        self.hg_extend = None

    def getName(self):
        return "黄果短剧"

    def init(self, extend=""):
        self.hg_extend = extend

    def destroy(self):
        pass

    def isVideoFormat(self, url):

        return bool(
            re.search(
                r"\.(?:m3u8|mp4)(?:\?|$)",
                str(url),
                re.I
            )
        )

    def manualVideoCheck(self):
        return False

    # --------------------------------------------------------
    # 封面代理
    # --------------------------------------------------------

    def _cover_proxy(self, url):

        url = cover(url)

        if not url:
            return ""

        try:
            return self.proxyUrl(
                {
                    "type": "cover",
                    "url": url
                },
                local=True
            )

        except Exception as exc:
            print(
                "[Huangguo] create cover proxy failed:",
                repr(exc)
            )
            return url

    def _proxy_pics(self, items):

        result = []

        for item in items or []:

            row = dict(item)

            row["vod_pic"] = self._cover_proxy(
                row.get("vod_pic", "")
            )

            row.pop("_episode_count", None)

            result.append(row)

        return result

    # --------------------------------------------------------
    # 首页
    # --------------------------------------------------------

    def homeContent(self, filter=False):

        filters = {}

        choices = [
            {"n": "最近更新", "v": "latest"},
            {"n": "当前热播", "v": "hot_window"},
            {"n": "集数最多", "v": "episode_count"}
        ]

        for item in CLASSES:

            if item["type_id"] == "ranks/hot":
                continue

            filters[item["type_id"]] = [
                {
                    "key": "sort",
                    "name": "排序",
                    "init": "latest",
                    "value": choices
                }
            ]

        return {
            "class": CLASSES,
            "filters": filters
        }

    def homeVideoContent(self):

        page = fetch(self, SITE + "/")

        items = parse_cards(page, all_grids=True)

        return {
            "list": self._proxy_pics(items)
        }

    # --------------------------------------------------------
    # 分类
    # --------------------------------------------------------

    def categoryContent(
        self,
        tid,
        pg,
        filter=False,
        extend=None
    ):

        try:
            page = max(1, int(pg or 1))
        except Exception:
            page = 1

        if tid == "ranks/hot":

            html = fetch(
                self,
                SITE + "/ranks/hot/"
            )

            items = parse_ranks(html)

            return {
                "list": self._proxy_pics(items),
                "page": page,
                "pagecount": 1,
                "limit": 20,
                "total": len(items)
            }

        sort = ""

        if isinstance(extend, dict):
            sort = str(extend.get("sort") or "")

        elif isinstance(extend, str):
            obj = json_load(extend, {})
            if isinstance(obj, dict):
                sort = str(obj.get("sort") or "")

        path = str(tid or "").strip("/")

        # 集数排序：尝试 JSON API
        if sort in ("hot_window", "episode_count"):

            api_list, pages, total = api_category(
                self,
                path,
                page,
                sort
            )

            if api_list:

                return {
                    "list": self._proxy_pics(api_list),
                    "page": page,
                    "pagecount": max(page, pages or page),
                    "limit": 21,
                    "total": total or len(api_list)
                }

        # 默认排序：先尝试 JSON API
        if sort in ("", "latest"):

            api_list, pages, total = api_category(
                self,
                path,
                page,
                ""
            )

            if api_list:

                return {
                    "list": self._proxy_pics(api_list),
                    "page": page,
                    "pagecount": max(page, pages or page),
                    "limit": 21,
                    "total": total or len(api_list)
                }

        # HTML 备用
        url = (
            SITE + "/" + path + "/"
            if page <= 1
            else SITE + "/" + path + "/" + str(page) + "/"
        )

        html = fetch(self, url)

        items = parse_cards(html)

        pages = page + 1 if len(items) >= 20 else page

        return {
            "list": self._proxy_pics(items),
            "page": page,
            "pagecount": pages,
            "limit": 20,
            "total": pages * 20
        }

    # --------------------------------------------------------
    # 详情
    # --------------------------------------------------------

    def detailContent(self, ids):

        vid = str(
            ids[0]
            if isinstance(ids, (list, tuple)) and ids
            else ids or ""
        ).strip()

        if not re.fullmatch(r"\d+", vid):
            return {"list": []}

        # 先请求 JSON 详情
        api_data = api_detail(self, vid)

        # 页面仍然作为备用和集数来源
        page = fetch(
            self,
            SITE + "/video/" + vid + "/"
        )

        if not page and not api_data:
            return {"list": []}

        title = (
            clean(match(r"<h1\b[^>]*>(.*?)</h1>", page))
            or clean(match(r"<title\b[^>]*>(.*?)</title>", page))
            or str(api_data.get("title") or vid)
        )

        title = title.split(" - ")[0].strip()

        data = initial_data(page)

        pic = (
            data.get("coverSrc")
            or api_data.get("cover")
            or api_data.get("cover_src")
            or match(
                r'<meta\b[^>]*(?:property|name)=["\']og:image["\']'
                r'[^>]*content=["\']([^"\']+)',
                page
            )
        )

        playlist = []

        for ep, url in episodes(page, vid):

            playlist.append(
                "第%s集$%s|||%s" % (
                    ep,
                    url,
                    ep
                )
            )

        vod = {
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": self._cover_proxy(cover(pic)),
            "vod_play_from": "黄果",
            "vod_play_url": "#".join(playlist)
        }

        tag_block = match(
            r'<div\b(?=[^>]*class=["\'][^"\']*'
            r'\bhg-web-play__tags\b[^"\']*["\'])'
            r'[^>]*>(.*?)</div>',
            page
        )

        tag_names = []

        for item in re.finditer(
            r'<a\b[^>]*href=["\'][^"\']*/tag/'
            r'([A-Za-z0-9_-]+)/?["\'][^>]*>(.*?)</a>',
            tag_block,
            re.I | re.S
        ):

            name = clean(item.group(2))

            if name and name not in tag_names:
                tag_names.append(name)

        if tag_names:
            vod["vod_content"] = "相关标签：" + "、".join(tag_names)

        return {
            "list": [vod]
        }

    # --------------------------------------------------------
    # 搜索
    # --------------------------------------------------------

    def searchContent(self, key, quick=False, pg="1"):

        try:
            page = max(1, int(pg or 1))
        except Exception:
            page = 1

        keyword = str(key or "").strip()

        if not keyword:
            return {
                "list": [],
                "page": page,
                "pagecount": page
            }

        # 优先 JSON API
        items = api_search(
            self,
            keyword,
            page
        )

        # HTML 备用
        if not items:

            url = (
                SITE
                + "/search/video/"
                + quote(keyword, safe="")
                + "/"
            )

            if page > 1:
                url += str(page) + "/"

            html = fetch(self, url)

            items = parse_cards(html)

        return {
            "list": self._proxy_pics(items),
            "page": page,
            "pagecount": page + 1 if items else page,
            "limit": 20,
            "total": len(items)
        }

    # --------------------------------------------------------
    # 播放
    # --------------------------------------------------------

    def playerContent(self, flag, id, vipFlags=None):

        parts = str(id or "").split("|||", 1)

        page_url = fix(parts[0])

        ep = parts[1] if len(parts) > 1 else "1"

        # 限定本站视频地址
        if not page_url.startswith(SITE + "/"):
            return {
                "parse": 0,
                "url": ""
            }

        vid = match(
            r"/video/(\d+)/",
            page_url
        )

        if not vid:
            return {
                "parse": 0,
                "url": ""
            }

        # 先使用加密协议
        play_url = encrypted_play(
            self,
            vid,
            ep
        )

        # 加密协议失败时，检查页面是否存在公开播放地址
        if not play_url:

            html = fetch(
                self,
                page_url,
                SITE + "/"
            )

            play_url = extract_play(
                html,
                ep
            )

        return {
            "parse": 0,
            "url": play_url,
            "header": {
                "User-Agent": UA,
                "Referer": SITE + "/"
            }
        }

    # --------------------------------------------------------
    # 封面本地代理
    # --------------------------------------------------------

    def proxy(self, params):

        params = params or {}

        if str(params.get("type", "")) != "cover":
            return [
                404,
                "text/plain",
                "Unknown proxy type"
            ]

        url = str(params.get("url") or "")

        if not url.startswith(("https://", "http://")):
            return [
                400,
                "text/plain",
                "Invalid image URL"
            ]

        try:

            response = request(
                self,
                url,
                method="GET",
                buffer=2
            )

            if not response:
                return [
                    502,
                    "text/plain",
                    "Image download failed"
                ]

            status = response.get(
                "code",
                response.get("status", 0)
            )

            if str(status) != "200":
                return [
                    502,
                    "text/plain",
                    "Image HTTP error"
                ]

            result = decrypt_image(
                response.get("content", "")
            )

            if not result:
                return [
                    502,
                    "text/plain",
                    "Image decrypt failed"
                ]

            mime, encoded = result

            image_bytes = base64.b64decode(encoded)

            return [
                200,
                mime,
                image_bytes,
                {
                    "Cache-Control": "public, max-age=3600"
                }
            ]

        except Exception as exc:

            print(
                "[HG-COVER] proxy error:",
                repr(exc)
            )

            return [
                500,
                "text/plain",
                "Image proxy error"
            ]
