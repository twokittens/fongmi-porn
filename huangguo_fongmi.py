# -*- coding: utf-8 -*-
"""Huangguo FongMi Python Spider: categories, encrypted covers and dx150-edge-v1 playback."""
import re
import json
import base64
import binascii
import html as html_lib
from urllib.parse import urljoin, quote
from base.spider import Spider as BaseSpider

IMG_KEY = b'f5d965df75336270'
IMG_IV = b'97b60394abc2fbe1'
SITE = 'https://huangguoai.io'
UA = 'Mozilla/5.0 (Linux; Android 13; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
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
    return url if url.startswith(('https://', 'http://')) else ''

def image_from_card(fragment):
    """Read actual lazy-loaded image, not the placeholder in img.src."""
    tag = match(r'<img\b([^>]+)>', fragment)
    if not tag:
        return ''
    for attribute in ('data-src', 'data-original', 'data-lazy-src', 'src'):
        m = re.search(r'(?<![\w-])' + re.escape(attribute) + r"\s*=\s*([\"'])(.*?)\1", tag, re.I | re.S)
        if m:
            url = html_lib.unescape(m.group(2)).strip()
            if url and not url.startswith(('data:', 'blob:')) and 'cover-placeholder' not in url:
                return cover(url)
    return ''

def decrypt_image(raw):
    """FongMi buffer=2 supplies base64; decode AES-CBC/NoPadding image bytes."""
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

    if isinstance(raw, (bytes, bytearray)):
        payload = bytes(raw)
        # Some bridges return base64 bytes instead of the original image bytes.
        if not mime_of(payload) and len(payload) > 24 and re.fullmatch(rb'[A-Za-z0-9+/=\r\n]+', payload):
            try:
                payload = base64.b64decode(payload, validate=False)
            except (ValueError, binascii.Error):
                pass
    elif isinstance(raw, str):
        value = raw.strip()
        if value.startswith('data:') and ',' in value:
            value = value.split(',', 1)[1]
        try:
            payload = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            print('[HG-COVER] buffer content is not base64')
            return None
    else:
        print('[HG-COVER] unsupported content type:', type(raw).__name__)
        return None

    mime = mime_of(payload)
    if mime:
        return mime, base64.b64encode(payload).decode('ascii')
    if not payload:
        return None

    # CryptoJS NoPadding zero-fills a non-block-aligned final cipher block.
    # The worker does the same and truncates plaintext to the original length.
    original_length = len(payload)
    padded = payload + bytes((-original_length) % 16)
    decrypted = None
    try:
        from Crypto.Cipher import AES
        decrypted = AES.new(IMG_KEY, AES.MODE_CBC, IMG_IV).decrypt(padded)
    except ImportError:
        try:
            from Cryptodome.Cipher import AES
            decrypted = AES.new(IMG_KEY, AES.MODE_CBC, IMG_IV).decrypt(padded)
        except ImportError:
            try:
                from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
                dec = Cipher(algorithms.AES(IMG_KEY), modes.CBC(IMG_IV)).decryptor()
                decrypted = dec.update(padded) + dec.finalize()
            except ImportError:
                print('[HG-COVER] no AES library available')
                return None
    if decrypted is None:
        return None
    decrypted = decrypted[:original_length]
    mime = mime_of(decrypted)
    if not mime:
        print('[HG-COVER] decrypted bytes not recognized as image; size:', original_length)
        return None
    return mime, base64.b64encode(decrypted).decode('ascii')

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

def page_count(page, default=1):
    """Read the site's explicit pager page count, then fall back to pager URLs."""
    source = page or ''
    # Tag archives expose the authoritative page count in hg-pager__jump.
    m = re.search(
        r'<(?:span|div)\b(?=[^>]*class=["\'][^"\']*\bhg-pager__jump\b[^"\']*["\'])'
        r'[^>]*\bdata-pages=["\'](\d+)["\']',
        source, re.I | re.S
    )
    if m:
        return max(1, int(m.group(1)))

    nums = [1]
    for href in re.findall(r'href=["\']([^"\']+)', source, re.I):
        path = html_lib.unescape(href).split('?', 1)[0].rstrip('/')
        if re.search(r'/(?:video|detail|search)(?:/|$)', path, re.I):
            continue
        m = re.search(r'/page/(\d+)$', path, re.I)
        if m:
            nums.append(int(m.group(1)))
        elif re.search(r'/tag/', path, re.I):
            continue
        else:
            m = re.search(r'/(\d+)$', path)
            if m:
                nums.append(int(m.group(1)))
    for pat in (r'data-total-pages=["\'](\d+)', r'"total_pages"\s*:\s*(\d+)',
                r'"pagecount"\s*:\s*(\d+)'):
        nums.extend(int(value) for value in re.findall(pat, source, re.I))
    return max(nums) if len(nums) > 1 else default


def category_page_url(path, page):
    """The site's category pagination uses /<category>/<page>/, not /page/<N>/."""
    base = SITE + '/' + str(path).strip('/') + '/'
    return base if page <= 1 else base + str(page) + '/'


def tag_page_url(slug, page):
    """Tag archives use /tag/<slug>/page/<N>/, unlike category archives."""
    base = SITE + '/tag/' + slug.strip('/') + '/'
    return base if page <= 1 else base + 'page/' + str(page) + '/'


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
            pic = image_from_card(b)
            ep_tag = match(r'(<span\b[^>]*class=["\'][^"\']*hg-drama-card__episode[^"\']*["\'][^>]*>)', b)
            ep_base = match(r'data-ep-base=[\\"\']([^\\"\']+)', ep_tag) or ''
            ep = clean(match(r'hg-drama-card__episode[^>]*>(.*?)</span>', b))
            score = clean(match(r'hg-drama-card__score[^>]*>(.*?)</span>', b))
            count_text = ep_base or ep
            count_match = re.search(r'(\d+)', count_text)
            episode_count = int(count_match.group(1)) if count_match else 0
            seen.add(vid)
            result.append({'vod_id': vid, 'vod_name': title, 'vod_pic': cover(pic),
                           'vod_remarks': ' · '.join(x for x in (ep, score) if x),
                           '_episode_count': episode_count})
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
        result.append({'vod_id': vid, 'vod_name': title, 'vod_pic': image_from_card(b), 'vod_remarks': clean(match(r'hg-rank-item__tags[^>]*>(.*?)</div>', b))})
        if len(result) >= 20:
            break
    return result

def api_cards(data):
    """Convert the site's category JSON items into FongMi VOD cards."""
    if not isinstance(data, dict):
        return []
    raw_items = data.get('items') or data.get('list') or []
    result, seen = [], set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        vid = str(item.get('id') or item.get('video_id') or '')
        title = clean(str(item.get('title') or item.get('name') or ''))
        if not vid or not vid.isdigit() or not title or vid in seen:
            continue
        pic = item.get('cover') or item.get('cover_src') or item.get('image') or ''
        tags = item.get('tags') or []
        if isinstance(tags, str):
            tags = [x.strip() for x in re.split(r'[,，、|]', tags) if x.strip()]
        episode_count = item.get('episode_count') or item.get('total_episodes') or 0
        finished = bool(item.get('is_finished'))
        remarks = ('全%s集' % episode_count) if finished and episode_count else (('更新至%s集' % episode_count) if episode_count else '')
        score = item.get('score')
        if score:
            remarks = ' · '.join(x for x in (remarks, str(score) + '分') if x)
        result.append({'vod_id': vid, 'vod_name': title, 'vod_pic': cover(pic),
                       'vod_remarks': remarks})
        seen.add(vid)
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
    # Some pages expose episode numbers only in videoInitialData.trackingEpisodes.
    # trackingEpisodes[*].video_id is metadata; playback uses drama ID + episode number,
    # matching the supplied project's playViaDx(id, ep) implementation.
    tracking = initial_data(page).get('trackingEpisodes') or {}
    if isinstance(tracking, dict):
        for episode_key in tracking.keys():
            ep_key = str(episode_key)
            if re.fullmatch(r'\d+', ep_key):
                result.setdefault(str(int(ep_key)), SITE + '/video/' + vid + '/')
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

# ===== dx150-edge-v1 playback protocol =====
# Mirrors the protocol implementation in the supplied app.js / worker/index.js.
DX_PROTOCOL = 'dx150-edge-v1'
DX_PLAYBACK_ENDPOINT = '/api/playback/request'


def _b64u_decode(value):
    value = str(value or '').replace('-', '+').replace('_', '/')
    value += '=' * ((4 - len(value) % 4) % 4)
    return base64.b64decode(value)


def _b64u_encode(value):
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def _hkdf_sha256(ikm, salt, info, length=32):
    # RFC 5869 HKDF-Extract + HKDF-Expand.
    prk = __import__('hmac').new(salt, ikm, hashlib.sha256).digest()
    out, block, counter = b'', b'', 1
    while len(out) < length:
        block = __import__('hmac').new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


class DXCrypto(object):
    """Small adapter supporting either cryptography or PyCryptodome."""
    def __init__(self):
        self.backend = ''
        self.private = None
        self.req_key = None
        self.res_key = None
        self.info = ''
        self.kid = ''
        self.sid = ''
        self.seq = 0
        self.time_offset = 0
        self.expires_at = 0
        self._init_backend()

    def _init_backend(self):
        try:
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.hkdf import HKDF
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            self.backend = 'cryptography'
            self.ec = ec
            self.AESGCM = AESGCM
            return
        except Exception:
            pass
        try:
            from Crypto.PublicKey import ECC
            from Crypto.Cipher import AES
            self.backend = 'pycryptodome'
            self.ECC = ECC
            self.AES = AES
            return
        except Exception as exc:
            raise RuntimeError('缺少加密依赖：需要 cryptography 或 pycryptodome；当前环境无法执行 ECDH/AES-GCM：' + str(exc))

    def _new_keypair(self):
        if self.backend == 'cryptography':
            key = self.ec.generate_private_key(self.ec.SECP256R1())
            nums = key.public_key().public_numbers()
            pub = b'\x04' + nums.x.to_bytes(32, 'big') + nums.y.to_bytes(32, 'big')
            return key, pub
        key = self.ECC.generate(curve='P-256')
        pub = b'\x04' + int(key.pointQ.x).to_bytes(32, 'big') + int(key.pointQ.y).to_bytes(32, 'big')
        return key, pub

    def _derive_shared(self, private, server_pub):
        if len(server_pub) != 65 or server_pub[0] != 4:
            raise ValueError('服务端 P-256 公钥格式错误')
        x = int.from_bytes(server_pub[1:33], 'big')
        y = int.from_bytes(server_pub[33:65], 'big')
        if self.backend == 'cryptography':
            from cryptography.hazmat.primitives.asymmetric import ec
            public = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
            return private.exchange(ec.ECDH(), public)
        point = self.ECC.EccPoint(x, y, curve='NIST P-256')
        shared_point = point * int(private.d)
        return int(shared_point.x).to_bytes(32, 'big')

    def _aes_encrypt(self, key, nonce, plain, aad):
        if self.backend == 'cryptography':
            return self.AESGCM(key).encrypt(nonce, plain, aad)
        cipher = self.AES.new(key, self.AES.MODE_GCM, nonce=nonce, mac_len=16)
        cipher.update(aad)
        encrypted, tag = cipher.encrypt_and_digest(plain)
        return encrypted + tag

    def _aes_decrypt(self, key, nonce, cipher_text, aad):
        if self.backend == 'cryptography':
            return self.AESGCM(key).decrypt(nonce, cipher_text, aad)
        if len(cipher_text) < 16:
            raise ValueError('AES-GCM 响应密文长度不足')
        cipher = self.AES.new(key, self.AES.MODE_GCM, nonce=nonce, mac_len=16)
        cipher.update(aad)
        return cipher.decrypt_and_verify(cipher_text[:-16], cipher_text[-16:])

    def open(self, spider):
        private, client_pub = self._new_keypair()
        hello_body = {
            'v': 1,
            'type': 'hello',
            'client_pub': _b64u_encode(client_pub)
        }
        hello = post_json(spider, SITE + DX_PLAYBACK_ENDPOINT, hello_body)
        if not isinstance(hello, dict) or hello.get('v') != 1 or hello.get('type') != 'hello':
            raise ValueError('DX 握手响应格式不正确：' + str(hello)[:300])
        for field in ('server_pub', 'salt', 'kid', 'sid', 'site', 'server_time', 'expires_at'):
            if field not in hello:
                raise ValueError('DX 握手缺少字段：' + field)
        shared = self._derive_shared(private, _b64u_decode(hello['server_pub']))
        salt = _b64u_decode(hello['salt'])
        self.info = '\n'.join([DX_PROTOCOL, 'playback', str(hello['site']), str(hello['kid']), str(hello['sid'])])
        self.req_key = _hkdf_sha256(shared, salt, (self.info + '\nreq').encode('utf-8'), 32)
        self.res_key = _hkdf_sha256(shared, salt, (self.info + '\nres').encode('utf-8'), 32)
        now = int(__import__('time').time())
        self.time_offset = int(hello['server_time']) - now
        self.expires_at = now + int(hello['expires_at']) - int(hello['server_time'])
        self.kid = str(hello['kid'])
        self.sid = str(hello['sid'])
        self.seq = 0

    def call(self, spider, method, path, obj=None):
        now = int(__import__('time').time())
        if not self.req_key or self.expires_at <= now + 5:
            self.open(spider)
        self.seq += 1
        seq = self.seq
        ts = int(__import__('time').time()) + self.time_offset
        nonce = b'\x00' * 8 + int(seq).to_bytes(4, 'big')
        if obj is None:
            body = b''
            content_type = ''
        else:
            body = json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            content_type = 'application/json'
        packet = {
            'method': str(method).upper(),
            'path': str(path),
            'body': base64.b64encode(body).decode('ascii'),
            'content_type': content_type,
            'visitor_id': ''
        }
        aad_req = '\n'.join([self.info, 'req', str(seq), str(ts)]).encode('utf-8')
        plain = json.dumps({'request': packet}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        encrypted = self._aes_encrypt(self.req_key, nonce, plain, aad_req)
        envelope = {
            'v': 1, 'type': 'call', 'kid': self.kid, 'sid': self.sid,
            'seq': seq, 'ts': ts, 'ciphertext': _b64u_encode(encrypted)
        }
        try:
            response = post_json(spider, SITE + DX_PLAYBACK_ENDPOINT, envelope)
            if not isinstance(response, dict) or not response.get('ciphertext'):
                raise ValueError('DX 加密响应缺少 ciphertext：' + str(response)[:300])
            aad_res = '\n'.join([self.info, 'res', str(seq), str(ts)]).encode('utf-8')
            decrypted = self._aes_decrypt(self.res_key, nonce, _b64u_decode(response['ciphertext']), aad_res)
            inner = json.loads(decrypted.decode('utf-8'))
            status = int(inner.get('status') or 0)
            raw_body = base64.b64decode(inner.get('body') or '')
            body_text = raw_body.decode('utf-8', errors='replace')
            return status, body_text
        except Exception:
            # A failed sequence must never be reused with the same AES-GCM key/nonce.
            self.req_key = None
            self.res_key = None
            self.expires_at = 0
            raise


def _response_json(response):
    if isinstance(response, dict):
        content = response.get('content', '')
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='replace')
        if isinstance(content, dict):
            return content
        return json.loads(str(content or '{}'))
    if isinstance(response, bytes):
        response = response.decode('utf-8', errors='replace')
    return json.loads(str(response or '{}'))


def post_json(spider, url, payload):
    """FongMi net.req POST wrapper; never sends browser-only Origin headers."""
    headers = dict(HEADERS)
    headers['Content-Type'] = 'application/json'
    headers['Accept'] = 'application/json, text/plain, */*'
    try:
        response = spider.net.req(url, {
            'method': 'POST',
            'timeout': 30000,
            'headers': headers,
            'cookie': True,
            'data': json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        })
    except TypeError:
        # Compatibility with FongMi builds that expose post data as `body`.
        response = spider.net.req(url, {
            'method': 'POST', 'timeout': 30000,
            'headers': headers, 'cookie': True,
            'body': json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        })
    if isinstance(response, str):
        response = json.loads(response)
    if not isinstance(response, dict):
        raise TypeError('net.req POST 返回类型异常：' + type(response).__name__)
    status = int(response.get('code', response.get('status', 0)) or 0)
    if status and status not in (200, 201):
        content = response.get('content', '')
        raise RuntimeError('HTTP %s: %s' % (status, str(content)[:200]))
    return _response_json(response)


def playback_url(spider, video_id, episode):
    """Request the source's encrypted per-episode playback API."""
    if not re.fullmatch(r'\d+', str(video_id)):
        raise ValueError('剧集 ID 非法：' + str(video_id))
    if not re.fullmatch(r'\d+', str(episode)):
        raise ValueError('集数参数非法：' + str(episode))
    client = DXCrypto()
    status, body = client.call(
        spider, 'POST',
        '/api/videos/%s/episodes/%s/playback' % (video_id, episode),
        {}
    )
    if status != 200:
        raise RuntimeError('播放接口业务状态码：%s；响应：%s' % (status, body[:500]))
    try:
        payload = json.loads(body)
    except Exception as exc:
        raise ValueError('播放接口返回不是 JSON：' + body[:300]) from exc
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError('播放响应缺少 data：' + str(payload)[:500])
    streams = data.get('streams') or {}
    if not isinstance(streams, dict):
        streams = {}
    url = streams.get('main') or streams.get('preview') or ''
    if isinstance(url, dict):
        url = url.get('url') or ''
    url = str(url or '').replace('\\u0026', '&').replace('\\/', '/')
    if not url.startswith(('http://', 'https://')):
        raise ValueError('加密接口已响应，但 streams.main/preview 没有有效地址：' + str(streams)[:500])
    return url


class Spider(BaseSpider):
    def __init__(self):
        super().__init__()
        self.hg_extend = None

    def _cover_proxy(self, url):
        url = cover(url)
        if not url:
            return ''
        try:
            return self.proxyUrl({'type': 'cover', 'url': url}, local=True)
        except Exception as exc:
            print('[Huangguo] create cover proxy failed:', repr(exc))
            return url

    def _proxy_pics(self, items):
        result = []
        for item in items or []:
            row = dict(item)
            row['vod_pic'] = self._cover_proxy(row.get('vod_pic', ''))
            row.pop('_episode_count', None)
            result.append(row)
        return result

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
        filters = {}
        choices = [
            {'n': '最近更新', 'v': 'latest'},
            {'n': '当前热播', 'v': 'hot_window'},
            {'n': '集数最多', 'v': 'episode_count'},
        ]
        for item in CLASSES:
            if item['type_id'] != 'ranks/hot':
                filters[item['type_id']] = [{
                    'key': 'sort', 'name': '排序', 'init': 'latest', 'value': choices
                }]
        return {'class': CLASSES, 'filters': filters}

    def _api_category(self, tid, page, sort):
        api = SITE + '/api/videos/category/' + quote(str(tid), safe='')
        params = []
        if sort and sort != 'latest':
            params.append('sort=' + quote(sort, safe='_'))
        params.extend(['page=' + str(page), 'size=21'])
        raw = fetch(self, api + '?' + '&'.join(params))
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {}
        payload = data.get('data') if isinstance(data, dict) else None
        if not isinstance(payload, dict):
            payload = data if isinstance(data, dict) else {}
        items = api_cards(payload)
        total = int(payload.get('total') or payload.get('total_count') or payload.get('totalItems') or 0)
        pages = int(payload.get('pages') or payload.get('total_pages') or 0)
        if not pages and total:
            pages = (total + 20) // 21
        return items, pages or (page + 1 if len(items) >= 21 else page), total

    def categoryContent(self, tid, pg, filter=False, extend=None):
        try:
            page = max(1, int(pg or 1))
        except (ValueError, TypeError):
            page = 1

        if tid == 'ranks/hot':
            items = parse_ranks(fetch(self, SITE + '/ranks/hot/'))
            return {'list': self._proxy_pics(items), 'page': 1,
                    'pagecount': 1, 'limit': 20, 'total': len(items)}

        # Tag archives use /tag/<slug>/page/<N>/ pagination.
        if str(tid).startswith('tag/'):
            slug = str(tid).split('/', 1)[1].strip('/')
            if not re.fullmatch(r'[A-Za-z0-9_-]+', slug):
                return {'list': [], 'page': page, 'pagecount': page, 'total': 0}
            url = tag_page_url(slug, page)
            html = fetch(self, url)
            items = parse_cards(html)
            # Some tag archives contain fewer than 20 cards per page while
            # still having more pages. Continue until an empty page is reached
            # when the archive does not expose a usable page count.
            pages = page_count(html, page if not items else page + 1)
            return {'list': self._proxy_pics(items), 'page': page,
                    'pagecount': max(page, pages), 'limit': 20,
                    'total': max(page, pages) * 20}

        path = str(tid or '').strip('/')
        sort = ''
        if isinstance(extend, dict):
            sort = str(extend.get('sort') or '')
        elif isinstance(extend, str):
            try:
                ext_obj = json.loads(extend)
                if isinstance(ext_obj, dict):
                    sort = str(ext_obj.get('sort') or '')
            except Exception:
                pass

        # "最近更新" is the site's native default ordering: do not append
        # any sort parameter and do not reorder the returned cards.
        if sort in ('', 'latest'):
            html = fetch(self, category_page_url(path, page))
            items = parse_cards(html)
            pages = page_count(html, page if not items else page + (1 if len(items) >= 20 else 0))
            return {'list': self._proxy_pics(items), 'page': page,
                    'pagecount': max(page, pages), 'limit': 20,
                    'total': max(page, pages) * 20}

        if sort == 'hot_window':
            # Dedicated hot feed only. Never fall back to the default/latest
            # category HTML: an unavailable hot endpoint must stay visibly empty.
            api_items, pages, total = self._api_category(path, page, 'hot_window')
            if not api_items:
                print('[Huangguo] hot category API returned no items:', path, page)
                return {'list': [], 'page': page, 'pagecount': max(page, pages),
                        'limit': 21, 'total': total}
            return {'list': self._proxy_pics(api_items), 'page': page,
                    'pagecount': max(page, pages), 'limit': 21,
                    'total': total or pages * 21}

        if sort == 'episode_count':
            # Fetch every category page first, then perform a global sort.
            # Sorting only the currently requested page gives incorrect results.
            all_items, seen = [], set()
            first_html = fetch(self, category_page_url(path, 1))
            if not first_html:
                return {'list': [], 'page': page, 'pagecount': page, 'total': 0}
            detected_pages = page_count(first_html, 0)
            first_batch = parse_cards(first_html)
            # If the site omits pagination metadata but returns a full page,
            # continue sequentially until the first short/empty page.
            last_page = detected_pages or (100 if len(first_batch) >= 20 else 1)
            for p in range(1, min(last_page, 100) + 1):
                html = first_html if p == 1 else fetch(self, category_page_url(path, p))
                if not html:
                    break
                batch = parse_cards(html)
                if not batch:
                    break
                for item in batch:
                    vid = str(item.get('vod_id') or '')
                    if vid and vid not in seen:
                        seen.add(vid)
                        all_items.append(item)
                # Stop at the first short page; this also handles sites whose
                # pagination metadata is missing or stale.
                if len(batch) < 20:
                    break
            all_items.sort(key=lambda x: int(x.get('_episode_count') or 0), reverse=True)
            total = len(all_items)
            page_size = 20
            pagecount = max(1, (total + page_size - 1) // page_size)
            selected = all_items[(page - 1) * page_size:page * page_size]
            return {'list': self._proxy_pics(selected), 'page': page,
                    'pagecount': pagecount, 'limit': page_size, 'total': total}

        # Unknown filter values must not silently alter the website's order.
        html = fetch(self, category_page_url(path, page))
        items = parse_cards(html)
        pages = page_count(html, page if not items else page + (1 if len(items) >= 20 else 0))
        return {'list': self._proxy_pics(items), 'page': page,
                'pagecount': max(page, pages), 'limit': 20,
                'total': max(page, pages) * 20}

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
        tag_links = []
        tag_names = []
        # Only read the current drama's tags; recommendation-card tags are elsewhere.
        tag_block = match(
            r"<div\b(?=[^>]*class=[\"'][^\"']*\bhg-web-play__tags\b[^\"']*[\"'])[^>]*>(.*?)</div>",
            page
        )
        for tag_match in re.finditer(
            r"<a\b[^>]*href=[\"']([^\"']*/tag/([A-Za-z0-9_-]+)/?)[\"'][^>]*>(.*?)</a>",
            tag_block, re.I | re.S
        ):
            slug, name = tag_match.group(2), clean(tag_match.group(3))
            if name and slug and name not in tag_names:
                tag_names.append(name)
                try:
                    tag_links.append(self.link(name, {'id': 'tag/' + slug}))
                except Exception:
                    tag_links.append(name)
        vod = {'vod_id': vid, 'vod_name': title, 'vod_pic': self._cover_proxy(cover(pic)),
               'vod_play_from': '黄果', 'vod_play_url': '#'.join(playlist)}
        if tag_links:
            # FongMi renders links embedded in the description as clickable tags.
            vod['vod_content'] = '相关标签：' + '、'.join(tag_links)
        return {'list': [vod]}

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
        # Detail playlist stores: <episode-page-url>|||<episode-number>.
        parts = str(id or '').split('|||', 1)
        raw_page = parts[0].strip()
        ep = parts[1].strip() if len(parts) > 1 else '1'
        # Accept both the current .io host and old .com URLs already cached by clients.
        m = re.search(r'/video/(\d+)', raw_page) or re.search(r'/detail/(\d+)', raw_page)
        if not m and re.fullmatch(r'\d+', raw_page):
            video_id = raw_page
        elif m:
            video_id = m.group(1)
        else:
            print('[Huangguo] invalid playback page:', raw_page)
            return {'parse': 0, 'url': ''}
        try:
            url = playback_url(self, video_id, ep)
            print('[Huangguo] playback OK: video=%s ep=%s' % (video_id, ep))
            return {
                'parse': 0,
                'url': url,
                'header': {
                    'User-Agent': UA,
                    'Referer': SITE + '/video/' + video_id + '/',
                    'Accept': '*/*'
                }
            }
        except Exception as exc:
            print('[Huangguo] playback failed: video=%s ep=%s error=%s' % (video_id, ep, repr(exc)))
            return {'parse': 0, 'url': ''}

    def proxy(self, params):
        """FongMi proxy callback: return decrypted image bytes, not a data URI."""
        if str((params or {}).get('type', '')) != 'cover':
            return [404, 'text/plain', 'Unknown proxy type']
        url = str((params or {}).get('url') or '')
        if not url.startswith(('https://', 'http://')):
            return [400, 'text/plain', 'Invalid image URL']
        try:
            response = self.net.req(url, {
                'method': 'GET', 'timeout': 25000,
                'headers': dict(HEADERS), 'buffer': 2
            })
            if isinstance(response, str):
                response = json.loads(response)
            if not isinstance(response, dict):
                return [502, 'text/plain', 'Unexpected image response']
            status = response.get('code', response.get('status', 0))
            if str(status) != '200':
                return [502, 'text/plain', 'Image download failed']
            result = decrypt_image(response.get('content', ''))
            if not result:
                return [502, 'text/plain', 'Image decrypt failed']
            mime, encoded = result
            image_bytes = base64.b64decode(encoded)
            return [200, mime, image_bytes,
                    {'Cache-Control': 'public, max-age=3600'}]
        except Exception as exc:
            print('[HG-COVER] proxy error:', repr(exc))
            return [500, 'text/plain', 'Image proxy error']
