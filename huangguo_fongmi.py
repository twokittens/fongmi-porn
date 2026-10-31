# -*- coding: utf-8 -*-
"""Huangguo FongMi Python Spider, based on huangguo_fongmi.js."""
import re
import json
import base64
import binascii
import html as html_lib
from urllib.parse import urljoin, quote
from base.spider import Spider as BaseSpider

IMG_KEY = b'f5d965df75336270'
IMG_IV = b'97b60394abc2fbe1'
SITE = 'https://huangguoai.com'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
HEADERS = {'User-Agent': UA, 'Referer': SITE + '/', 'Accept-Language': 'zh-CN,zh;q=0.9'}
CLASSES = [
    {'type_id': 'ai-duanju', 'type_name': 'AI成人短剧'},
    {'type_id': 'ai-manju', 'type_name': 'AI成人漫剧'},
    {'type_id': 'ai-huanlian', 'type_name': 'AI换脸'},
    {'type_id': 'ai-mogai', 'type_name': 'AI魔改'},
    {'type_id': 'ranks/hot', 'type_name': '排行榜'},
]

def match(pattern, text, flags=re.I | re.S):
    m = re.search(pattern, text or '', flags)
    return m.group(1) if m else ''

def clean(value):
    value = re.sub(r'<(?:script|style)\b[^>]*>.*?</(?:script|style)>', '', value or '', flags=re.I | re.S)
    return html_lib.unescape(re.sub(r'<[^>]+>', '', value)).strip()

def fix(url):
    return urljoin(SITE + '/', html_lib.unescape(str(url or '')))

def cover(url):
    url = fix(url) if url else ''
    return url.split('?', 1)[0] if url.startswith(('https://', 'http://')) else ''

def decrypt_image(raw):
    """Decrypt Huangguo AES-CBC cover; return (MIME, base64 image)."""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode('ascii')
        except Exception:
            return None
    raw = str(raw or '').strip()
    if raw.startswith('data:image/') and ',' in raw:
        raw = raw.split(',', 1)[1]
    try:
        payload = base64.b64decode(raw)
    except (ValueError, binascii.Error):
        return None
    def mime_of(data):
        if data.startswith(b'\xff\xd8\xff'):
            return 'image/jpeg'
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            return 'image/png'
        if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
            return 'image/webp'
        if data.startswith((b'GIF87a', b'GIF89a')):
            return 'image/gif'
        return ''
    mime = mime_of(payload)
    if mime:
        return mime, base64.b64encode(payload).decode('ascii')
    if not payload or len(payload) % 16:
        return None
    decrypted = None
    try:
        from Crypto.Cipher import AES
        decrypted = AES.new(IMG_KEY, AES.MODE_CBC, IMG_IV).decrypt(payload)
    except ImportError:
        try:
            from Cryptodome.Cipher import AES
            decrypted = AES.new(IMG_KEY, AES.MODE_CBC, IMG_IV).decrypt(payload)
        except ImportError:
            try:
                from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
                decryptor = Cipher(algorithms.AES(IMG_KEY), modes.CBC(IMG_IV)).decryptor()
                decrypted = decryptor.update(payload) + decryptor.finalize()
            except ImportError:
                return None
    if not decrypted:
        return None
    pad = decrypted[-1]
    if 1 <= pad <= 16 and decrypted.endswith(bytes([pad]) * pad):
        decrypted = decrypted[:-pad]
    if decrypted.startswith(b'\xff\xd8'):
        end = decrypted.rfind(b'\xff\xd9')
        if end >= 0:
            decrypted = decrypted[:end + 2]
    elif decrypted.startswith(b'\x89PNG'):
        end = decrypted.rfind(b'IEND\xaeB`\x82')
        if end >= 0:
            decrypted = decrypted[:end + 8]
    mime = mime_of(decrypted)
    return (mime, base64.b64encode(decrypted).decode('ascii')) if mime else None

def fetch(spider, url, referer=None):
    headers = dict(HEADERS)
    if referer:
        headers['Referer'] = referer
    try:
        response = spider.net.req(url, {
            'method': 'GET', 'timeout': 25000,
            'headers': headers, 'cookie': True
        })
        if isinstance(response, str):
            response = json.loads(response)
        if not isinstance(response, dict):
            raise TypeError('net.req returned ' + type(response).__name__)
        status = int(response.get('code', response.get('status', 0)) or 0)
        if status != 200:
            print('[Huangguo] HTTP', status, url)
            return ''
        content = response.get('content', '') or ''
        if isinstance(content, bytes):
            return content.decode('utf-8', errors='replace')
        return str(content)
    except Exception as e:
        print('[Huangguo] request failed:', url, str(e))
        return ''

def blocks(text, marker):
    starts = [m.end() for m in re.finditer(r'<div\b[^>]*class=["\'][^"\']*\b' + re.escape(marker) + r'\b[^"\']*["\'][^>]*>', text, re.I)]
    return [text[starts[i]:(starts[i + 1] if i + 1 < len(starts) else len(text))] for i in range(len(starts))]

def parse_cards(page, all_grids=False):
    grids = blocks(page, 'hg-card-grid')
    scopes = grids if all_grids else grids[:1]
    if not scopes:
        scopes = [page]
    result, seen = [], set()
    for scope in scopes:
        for b in blocks(scope, 'hg-drama-card'):
            vid = match(r'href=["\'][^"\']*/(?:detail|video)/(\d+)/', b)
            if not vid or vid in seen:
                continue
            title = clean(match(r'hg-drama-card__title[^>]*>(.*?)</a>', b))
            if not title:
                title = clean(match(r'<a\b[^>]*href=["\'][^"\']*/(?:detail|video)/\d+/[^>]*>(.*?)</a>', b))
            if not title:
                continue
            pic = match(r'(?:data-src|src)=["\']([^"\']+)', b)
            ep = clean(match(r'hg-drama-card__episode[^>]*>(.*?)</span>', b))
            score = clean(match(r'hg-drama-card__score[^>]*>(.*?)</span>', b))
            seen.add(vid)
            result.append({'vod_id': vid, 'vod_name': title, 'vod_pic': cover(pic), 'vod_remarks': ' · '.join(x for x in (ep, score) if x)})
    if not result:
        for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']*/video/(\d+)/)[^"\']*["\'][^>]*>(.*?)</a>', page, re.I | re.S):
            vid, title = m.group(2), re.sub(r'全集在线观看$', '', clean(m.group(3))).strip()
            if vid not in seen and title and not title.isdigit():
                seen.add(vid)
                result.append({'vod_id': vid, 'vod_name': title, 'vod_pic': '', 'vod_remarks': ''})
    return result

def parse_ranks(page):
    rank = match(r'(<div\b[^>]*class=["\'][^"\']*hg-rank-list[^"\']*["\'][^>]*>.*)', page) or page
    result, seen = [], set()
    for b in blocks(rank, 'hg-rank-item'):
        vid = match(r'href=["\'][^"\']*/(?:detail|video)/(\d+)/', b)
        if not vid or vid in seen:
            continue
        title = clean(match(r'hg-rank-item__title[^>]*>(.*?)</h2>', b))
        if not title:
            title = clean(match(r'<a\b[^>]*href=["\'][^"\']*/(?:detail|video)/\d+/[^>]*>(.*?)</a>', b))
        if not title:
            continue
        seen.add(vid)
        result.append({'vod_id': vid, 'vod_name': title, 'vod_pic': cover(match(r'(?:data-src|src)=["\']([^"\']+)', b)), 'vod_remarks': clean(match(r'hg-rank-item__tags[^>]*>(.*?)</div>', b))})
        if len(result) >= 20:
            break
    return result

def initial_data(page):
    raw = match(r'<script\b[^>]*id=["\']videoInitialData["\'][^>]*>(.*?)</script>', page)
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {}

def episodes(page, vid):
    result = {}
    # Only accept links explicitly belonging to the selected video.
    pattern = r'<a\b[^>]*href=["\']([^"\']*/(?:video|detail)/' + re.escape(vid) + r'/[^"\']*)["\'][^>]*>.*?</a>'
    for m in re.finditer(pattern, page, re.I | re.S):
        tag, url = m.group(0), fix(m.group(1))
        ep = match(r'data-ep-id=["\'](\d+)', tag) or match(r'/ep-(\d+)/?', url)
        if not ep:
            ep = match(r'(\d+)', clean(tag))
        ep = str(int(ep)) if ep else '1'
        result.setdefault(ep, url)
    for m in re.finditer(r'href=["\']([^"\']*/video/' + re.escape(vid) + r'/(?:ep-(\d+)/)?)', page, re.I):
        result.setdefault(m.group(2) or '1', fix(m.group(1)))
    if not result:
        result['1'] = SITE + '/video/' + vid + '/'
    return sorted(result.items(), key=lambda pair: int(pair[0]))

def extract_play(page, ep):
    data = initial_data(page)
    srcs = data.get('epPlaySrcs') or {}
    url = srcs.get(str(ep)) or data.get('videoSrc') or ''
    if not isinstance(url, str):
        url = ''
    url = url.replace('\\u0026', '&').replace('\\/', '/')
    if not url:
        url = match(r'(https?:\\?/\\?/[^"\'<>\s]+?\.m3u8(?:\?[^"\'<>\s]*)?)', page)
    url = fix(url) if url else ''
    return url if url.startswith(('http://', 'https://')) else ''

class Spider(BaseSpider):
    def __init__(self):
        super().__init__()
        self.hg_extend = None

    def getName(self):
        return '黄果短剧'

    def init(self, extend=''):
        self.hg_extend = extend

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(?:m3u8|mp4)(?:\?|$)', str(url), re.I))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def homeContent(self, filter=False):
        return {'class': CLASSES}

    def _cover_proxy(self, url):
        if not url:
            return ''
        try:
            proxy = self.getProxyUrl()
            if proxy:
                separator = '&' if '?' in proxy else '?'
                return proxy + separator + 'url=' + quote(url, safe='')
        except Exception:
            pass
        return url

    def _proxy_pics(self, items):
        for item in items:
            if item.get('vod_pic'):
                item['vod_pic'] = self._cover_proxy(item['vod_pic'])
        return items

    def homeVideoContent(self):
        return {'list': self._proxy_pics(parse_cards(fetch(self, SITE + '/'), True))}

    def categoryContent(self, tid, pg, filter=False, extend=None):
        try:
            page = max(1, int(pg or 1))
        except (ValueError, TypeError):
            page = 1
        if tid == 'ranks/hot':
            return {'list': self._proxy_pics(parse_ranks(fetch(self, SITE + '/ranks/hot/'))), 'page': 1, 'pagecount': 1, 'limit': 20, 'total': 20}
        path = str(tid or '').strip('/')
        url = SITE + '/' + path + '/' + (str(page) + '/' if page > 1 else '')
        items = self._proxy_pics(parse_cards(fetch(self, url)))
        return {'list': items, 'page': page, 'pagecount': page + 1 if items else page, 'limit': len(items) or 20, 'total': (page + 1) * len(items) if items else page * 20}

    def detailContent(self, ids):
        vid = str(ids[0] if isinstance(ids, (list, tuple)) and ids else ids or '').strip()
        if not re.fullmatch(r'\d+', vid):
            return {'list': []}
        page = fetch(self, SITE + '/video/' + vid + '/')
        if not page:
            return {'list': []}
        data = initial_data(page)
        title = clean(match(r'<h1\b[^>]*>(.*?)</h1>', page)) or clean(match(r'<title\b[^>]*>(.*?)</title>', page)).split(' - ')[0] or vid
        pic = data.get('coverSrc') or match(r'<meta\b[^>]*(?:property|name)=["\']og:image["\'][^>]*content=["\']([^"\']+)', page)
        if not pic:
            pic = match(r'<meta\b[^>]*content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']og:image["\']', page)
        playlist = ['第%s集$%s|||%s' % (ep, url, ep) for ep, url in episodes(page, vid)]
        return {'list': [{'vod_id': vid, 'vod_name': title, 'vod_pic': self._cover_proxy(cover(pic)), 'vod_play_from': '黄果', 'vod_play_url': '#'.join(playlist)}]}

    def searchContent(self, key, quick=False, pg='1'):
        try:
            page = max(1, int(pg or 1))
        except (TypeError, ValueError):
            page = 1
        if not str(key or '').strip():
            return {'list': [], 'page': page, 'pagecount': page}
        url = SITE + '/search/video/' + quote(str(key).strip(), safe='') + '/' + (str(page) + '/' if page > 1 else '')
        items = self._proxy_pics(parse_cards(fetch(self, url)))
        return {'list': items, 'page': page, 'pagecount': page + 1 if items else page, 'limit': len(items) or 20, 'total': (page + 1) * len(items) if items else page * 20}

    def playerContent(self, flag, id, vipFlags=None):
        parts = str(id or '').split('|||', 1)
        page_url = fix(parts[0])
        if not page_url.startswith(SITE + '/'):
            return {'parse': 0, 'url': ''}
        ep = parts[1] if len(parts) > 1 else '1'
        url = extract_play(fetch(self, page_url, SITE + '/'), ep)
        return {'parse': 0, 'url': url, 'header': {'User-Agent': UA, 'Referer': SITE + '/'}}

    def localProxy(self, param):
        try:
            url = str((param or {}).get('url') or '')
            if not url.startswith(('https://', 'http://')):
                return [404, 'text/plain', 'Invalid image URL']
            response = self.net.req(url, {
                'method': 'GET', 'timeout': 15000,
                'headers': dict(HEADERS), 'buffer': 2
            })
            if isinstance(response, str):
                response = json.loads(response)
            if not isinstance(response, dict) or int(response.get('code', 0)) != 200:
                return [404, 'text/plain', 'Image fetch failed']
            result = decrypt_image(response.get('content', ''))
            if not result:
                return [404, 'text/plain', 'Image decrypt failed']
            mime, data = result
            return [200, mime, data, {'Cache-Control': 'public, max-age=3600'}, 1]
        except Exception as error:
            print('[Huangguo] image proxy error:', str(error))
            return [500, 'text/plain', 'Image proxy error']
