# -*- coding: utf-8 -*-
"""MissAV FongMi Python Spider v1.4.3 (actress labels restored, shared native filters, directory labels, subtitles)."""
import re
import html
import json
import urllib.request
import urllib.error
from urllib.parse import urljoin, urlparse, quote, urlencode, parse_qs, unquote, urlsplit, urlunsplit, parse_qsl
from html.parser import HTMLParser
from base.spider import Spider as BaseSpider

HOST = 'https://missav.ai'
CATEGORIES = [
    {'type_id': '/dm301/cn/today-hot', 'type_name': '今日热门'},
    {'type_id': '/dm170/cn/weekly-hot', 'type_name': '本周热门'},
    {'type_id': '/dm273/cn/monthly-hot', 'type_name': '本月热门'},    
    {'type_id': '/dm817/cn/uncensored-leak', 'type_name': '无码流出'},
    {'type_id': '/dm278/cn/chinese-subtitle', 'type_name': '中文字幕'},
    {'type_id': '/dm539/cn/new', 'type_name': '最新更新'},
    {'type_id': '/dm635/cn/release', 'type_name': '新作上市'},
    {'type_id': '/dm63/cn/madou', 'type_name': '麻豆传媒'},
    {'type_id': '/cn/klive', 'type_name': '韩国直播'},
    {'type_id': '/cn/clive', 'type_name': '中国直播'},
    {'type_id': '/dm597/cn/fc2', 'type_name': 'FC2'},
    {'type_id': '/dm2208642/cn/heyzo', 'type_name': 'HEYZO'},
    {'type_id': '/dm42/cn/tokyohot', 'type_name': '东京热'},
    {'type_id': '/dm4551174/cn/1pondo', 'type_name': '一本道'},
    {'type_id': '/cn/actresses', 'type_name': '女优一览', 'type_flag': 1},
    {'type_id': '/cn/actresses/ranking', 'type_name': '女优排行', 'type_flag': 1},
    {'type_id': '/dm6840521/cn/caribbeancom', 'type_name': 'Caribbeancom'},
    {'type_id': '/dm91887/cn/caribbeancompr', 'type_name': 'Caribbeancompr'},
    {'type_id': '/dm6238682/cn/10musume', 'type_name': '10musume'},
    {'type_id': '/dm3600557/cn/pacopacomama', 'type_name': 'pacopacomama'},
    {'type_id': '/dm150/cn/gachinco', 'type_name': 'gachinco'},
    {'type_id': '/dm42/cn/xxxav', 'type_name': 'xxxav'},
    {'type_id': '/dm37/cn/marriedslash', 'type_name': '人妻斩'},
    {'type_id': '/dm33/cn/naughty4610', 'type_name': '顽皮4160'},
    {'type_id': '/dm37/cn/naughty0930', 'type_name': '顽皮0930'},
    {'type_id': '/cn/genres', 'type_name': '类型', 'type_flag': 1},
    {'type_id': '/cn/makers', 'type_name': '发行商', 'type_flag': 1},
]
SPECIAL_PATHS = ('/cn/actresses', '/cn/actresses/ranking', '/cn/genres', '/cn/makers')

# Site-side sorting and filtering. Values supplied by the site user.
SORT_OPTIONS = [
    ('最近更新', 'published_at'), ('发行日期', 'released_at'),
    ('收藏最多', 'saved'), ('今日浏览', 'today_views'),
    ('本周浏览', 'weekly_views'), ('本月浏览', 'monthly_views'),
    ('总浏览', 'views'),
]
CATEGORY_FILTER_OPTIONS = [
    ('单人作品', 'individual'), ('多人作品', 'multiple'),
    ('中文字幕', 'chinese-subtitle'),
]
SEARCH_FILTER_OPTIONS = [
    ('单人作品', 'individual'), ('日本AV', 'jav'),
    ('亚洲AV', 'asiaav'), ('无码流出', 'uncensored-leak'),
    ('无码影片', 'uncensored'), ('中文字幕', 'chinese-subtitle'),
]


def special_kind(path):
    p = urlsplit(absolute(path)).path.rstrip('/')
    if p == '/cn/actresses/ranking':
        return 'actresses'
    if p in ('/cn/actresses', '/cn/genres', '/cn/makers'):
        return p.split('/')[-1]
    return ''


def parse_directory(source, kind):
    """Parse directory cards using real MissAV markup; preserve source ordering.

    In actress cards, h4 is the name, img.alt is the fallback; p contains
    video counts/debut years and ranking badges are NOT names.
    """
    records = {}

    def plain(value):
        value = re.sub(r'<[^>]+>', ' ', str(value or ''))
        return re.sub(r'\s+', ' ', html.unescape(value)).strip()

    def attr(markup, key):
        match = re.search(r'(?<![\w-])' + re.escape(key) +
                          r'\s*=\s*([\x22\x27])(.*?)\1', markup, re.I | re.S)
        return html.unescape(match.group(2)).strip() if match else ''

    pattern = (r'<a\b(?P<attrs>[^>]*?)\bhref\s*=\s*'
               r'(?P<q>[\x22\x27]?)(?P<href>[^\s\x22\x27>]+)(?P=q)'
               r'[^>]*>(?P<body>.*?)</a\s*>')
    for match in re.finditer(pattern, source, re.I | re.S):
        url = absolute(match.group('href'))
        path = urlsplit(url).path.rstrip('/')
        if not re.search(r'(?:/dm\d+)?/cn/' + re.escape(kind) + r'/[^/]+$', path, re.I):
            continue
        if kind == 'actresses' and path.endswith('/ranking'):
            continue
        body = match.group('body')
        entry = records.setdefault(url, {'name': '', 'name_priority': 0, 'pic': '', 'count': ''})

        img = re.search(r'<img\b([^>]*)>', body, re.I | re.S)
        if img:
            image_attrs = img.group(1)
            if not entry['pic']:
                for key in ('data-src', 'data-original', 'data-lazy-src', 'src'):
                    pic = attr(image_attrs, key)
                    if pic and not pic.startswith('data:'):
                        entry['pic'] = absolute(pic)
                        break
            img_name = attr(image_attrs, 'alt') or attr(image_attrs, 'title')
            if img_name and entry['name_priority'] < 90:
                entry['name'], entry['name_priority'] = img_name, 90

        # Actual actress/ranking HTML uses <h4>NAME</h4>, followed by
        # <p>5701 条影片</p> and <p>2008 出道</p>. Never select those p labels.
        headings = re.findall(r'<h[1-6]\b[^>]*>(.*?)</h[1-6]\s*>', body, re.I | re.S)
        if headings:
            heading = plain(headings[0])
            if heading:
                entry['name'], entry['name_priority'] = heading, 120
        elif kind != 'actresses':
            # For genre/maker pages, span or plain anchor text may be the label.
            spans = re.findall(r'<span\b[^>]*>(.*?)</span\s*>', body, re.I | re.S)
            for candidate in spans + [body]:
                label = plain(candidate)
                label = re.sub(r'\s*\d[\d,]*\s*(?:条影片|部影片|部作品|个视频)\s*$', '', label)
                if label and not re.fullmatch(r'\d[\d,]*', label) and entry['name_priority'] < 50:
                    entry['name'], entry['name_priority'] = label, 50
                    break

        count = re.search(r'(\d[\d,]*)\s*(?:条影片|部影片|部作品|个视频|videos?|movies?)', plain(body), re.I)
        if count:
            entry['count'] = count.group(1).replace(',', '')

    result = []
    for url, entry in records.items():
        name = entry['name']
        if not name:
            name = unquote(urlsplit(url).path.rstrip('/').split('/')[-1]).replace('-', ' ').replace('_', ' ')
        actress = kind == 'actresses'
        result.append({
            'vod_id': url, 'vod_name': name,
            'vod_pic': entry['pic'] if actress else '',
            'vod_tag': 'folder', 'cate': {},
            'style': {'type': 'oval', 'ratio': 1.0} if actress else {'type': 'rect', 'ratio': 4.0},
            # FongMi oval cards may display remarks instead of the main name.
            'vod_remarks': name if actress else (entry['count'] + ' 部影片' if entry['count'] else '')
        })
    return result


def parse_search_actresses(source):
    """Only include actress links actually present in the returned search HTML."""
    class ActressLinks(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.active = []
            self.records = []

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == 'a':
                href = a.get('href', '')
                path = urlsplit(absolute(href)).path.rstrip('/')
                ok = bool(re.fullmatch(r'(?:/dm\d+)?/cn/actresses/[^/]+', path, re.I))
                self.active.append({'href': href, 'name': a.get('title', ''),
                                    'pic': '', 'text': [], 'ok': ok})
            elif tag == 'img' and self.active and self.active[-1]['ok']:
                card = self.active[-1]
                card['name'] = card['name'] or a.get('alt', '')
                for key in ('data-src', 'data-original', 'data-lazy-src', 'src'):
                    pic = a.get(key, '')
                    if pic and not pic.startswith(('data:', 'blob:')):
                        card['pic'] = absolute(pic)
                        break

        def handle_data(self, data):
            if self.active:
                self.active[-1]['text'].append(data)

        def handle_endtag(self, tag):
            if tag == 'a' and self.active:
                card = self.active.pop()
                if card['ok']:
                    self.records.append(card)

    parser = ActressLinks()
    parser.feed(source)
    result, seen = [], set()
    for card in parser.records:
        url = absolute(card['href'])
        if url in seen:
            continue
        seen.add(url)
        name = re.sub(r'\s+', ' ', html.unescape(card['name'] or ''.join(card['text']))).strip()
        if not name:
            name = unquote(urlsplit(url).path.rstrip('/').split('/')[-1]).replace('-', ' ')
        result.append({'vod_id': url, 'vod_name': name,
                       'vod_pic': card['pic'], 'vod_remarks': name,
                       'vod_tag': 'folder', 'cate': {},
                       'style': {'type': 'oval', 'ratio': 1.0}})
    return result


def filter_choices(options):
    return [{'n': '全部', 'v': ''}] + [{'n': n, 'v': v} for n, v in options]


def category_filter_config():
    return [
        {'key': 'sort', 'name': '排序', 'value': filter_choices(SORT_OPTIONS)},
        {'key': 'work_filter', 'name': '作品过滤', 'value': filter_choices(CATEGORY_FILTER_OPTIONS)},
    ]


def append_options(path, sort='', filters=()):
    """Append site query parameters without destroying existing page parameters."""
    parts = urlsplit(path)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k not in ('sort', 'filters', 'page')]
    if sort in {v for _, v in SORT_OPTIONS}:
        query.append(('sort', sort))
    allowed = {v for _, v in CATEGORY_FILTER_OPTIONS + SEARCH_FILTER_OPTIONS}
    for value in dict.fromkeys(filters):
        if value in allowed:
            query.append(('filters', value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(query), parts.fragment))


def parse_search_expression(text):
    """Search syntax: JUR-857|sort=views|filters=chinese-subtitle,jav.

    SearchContent has no `extend` argument in the standard Spider interface.
    This keeps native search usable without pretending it supports filter UI.
    """
    chunks = str(text or '').split('|')
    keyword = chunks[0].strip()
    sort = ''
    filters = []
    allowed = {v for _, v in SEARCH_FILTER_OPTIONS}
    for chunk in chunks[1:]:
        key, sep, value = chunk.strip().partition('=')
        if not sep:
            continue
        key, value = key.strip().lower(), value.strip()
        if key == 'sort' and value in {v for _, v in SORT_OPTIONS}:
            sort = value
        elif key in ('filters', 'filter'):
            filters.extend(v for v in re.split(r'[,;+]', value) if v in allowed)
    return keyword, sort, list(dict.fromkeys(filters))


UA = ('Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36')


def absolute(url):
    return urljoin(HOST + '/', html.unescape(str(url or '')))


def valid_video(url):
    """Accept video detail paths without imposing a narrow code regex.

    MissAV has nonstandard codes and suffixes; a restrictive pattern can
    silently discard legitimate search hits.
    """
    parsed = urlparse(absolute(url))
    if parsed.hostname not in ('missav.ai', 'www.missav.ai'):
        return False
    path = re.sub(r'^/dm\d+', '', parsed.path, flags=re.I)
    path = re.sub(r'^/(?:cn|en|ja)(?=/|$)', '', path, flags=re.I).strip('/')
    if not path or '/' in path:
        return False
    blocked = {'search', 'tags', 'tag', 'actresses', 'actress', 'genres',
               'genre', 'makers', 'maker', 'labels', 'label', 'series',
               'login', 'register', 'favorites', 'history', 'saved',
               'chinese-subtitle', 'uncensored-leak', 'uncensored',
               'jav', 'asiaav', 'individual', 'multiple', 'new'}
    return path.lower() not in blocked and bool(re.search(r'\d', path))


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards = []
        self.stack = []
        self.meta = {}
        self.title_text = []
        self.in_h1 = False
        self.anchor_count = 0
        self.image_count = 0
        self.links = []
        self.next_url = ''

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta':
            key = a.get('property') or a.get('name')
            if key:
                self.meta[key.lower()] = a.get('content', '')
        if tag == 'h1':
            self.in_h1 = True
        if tag == 'a':
            self.anchor_count += 1
            href = a.get('href', '')
            self.links.append(href)
            self.stack.append({'href': href, 'alt': a.get('alt', ''),
                               'img': None, 'text': []})
        elif tag == 'img':
            self.image_count += 1
            if self.stack:
                self.stack[-1]['img'] = a
        elif tag == 'link' and 'next' in a.get('rel', '').lower():
            self.next_url = a.get('href', '')

    def handle_data(self, data):
        if self.in_h1:
            self.title_text.append(data)
        if self.stack:
            self.stack[-1]['text'].append(data)

    def handle_endtag(self, tag):
        if tag == 'h1':
            self.in_h1 = False
        if tag == 'a' and self.stack:
            self.cards.append(self.stack.pop())


def parse_videos(source):
    parser = PageParser()
    parser.feed(source)
    result = []
    seen = set()
    for item in parser.cards:
        url = absolute(item['href'])
        if not valid_video(url) or url in seen:
            continue
        image = item['img'] or {}
        if not image and not item['alt']:
            continue
        pic = (image.get('data-src') or image.get('data-original') or
               image.get('data-lazy-src') or image.get('src') or '')
        if pic.startswith('data:'):
            pic = ''
        code = item['alt'] or urlparse(url).path.rstrip('/').split('/')[-1]
        name = (image.get('alt') or ' '.join(item['text']).strip() or code)
        seen.add(url)
        result.append({'vod_id': url, 'vod_name': name,
                       'vod_pic': absolute(pic) if pic else '',
                       'vod_remarks': code.upper(),
                       'style': {'type': 'rect', 'ratio': 1.78}})
    return result, parser


def unpack_player(source):
    """Decode the Dean Edwards P.A.C.K.E.R. form used by MissAV.

    This is string substitution only: it never executes website JavaScript.
    """
    blocks = []
    packed = re.compile(
        r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\("
        r"'((?:\\.|[^'\\])*)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*"
        r"'((?:\\.|[^'\\])*)'\.split\('\|'\)",
        re.S)

    def base_n(number, radix):
        digits = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
        if number == 0:
            return '0'
        out = ''
        while number:
            out = digits[number % radix] + out
            number //= radix
        return out

    for match in packed.finditer(source):
        payload, radix, count, dictionary = match.groups()
        radix, count = int(radix), int(count)
        if not 2 <= radix <= 62 or count > 10000:
            continue
        words = dictionary.split('|')
        # Decode JS string escapes used in the packed payload.
        payload = payload.replace("\\'", "'").replace('\\\\', '\\')
        for i in range(count - 1, -1, -1):
            word = words[i] if i < len(words) else ''
            if word:
                payload = re.sub(r'\b' + re.escape(base_n(i, radix)) + r'\b',
                                 lambda m, value=word: value, payload)
        blocks.append(payload)
    return blocks


def extract_sources(source):
    """Decode all independent streams without assuming JS variable names are resolutions.

    Each stream remains selectable even when a CDN playlist cannot be fetched.
    """
    found = []
    seen = set()
    scripts = unpack_player(source)
    # Unpacked player variables and ordinary uncompressed player scripts.
    for script in scripts + [source]:
        for name, raw in re.findall(
                r"\b(source(?:[0-9]+)?|playlist)\s*=\s*['\"]([^'\"]+)['\"]",
                script, re.I):
            url = html.unescape(raw.replace('\\/', '/'))
            if re.match(r'^https?://', url, re.I) and re.search(
                    r'\.(?:m3u8|mp4)(?:[?#]|$)', url, re.I):
                if url not in seen:
                    found.append((name.lower(), url))
                    seen.add(url)
    result = found
    if not result:
        fallback = extract_media(source)
        if fallback:
            result.append(('正片', fallback))
    return result


def stream_quality_hint(url):
    """Use an explicit media path as a quality hint, never source variable digits."""
    path = unquote(urlparse(url).path).lower()
    match = re.search(r'(?:^|[/_.-])(2160|1440|1080|720|480|360)p(?:[/_.-]|$)', path)
    if match:
        return match.group(1) + 'P'
    return ''


def quality_rank(label):
    match = re.search(r'(\d{3,4})P', label, re.I)
    return int(match.group(1)) if match else 0


def extract_media(source):
    # Only direct media URLs; do not treat short preview.mp4 as the feature video.
    patterns = [
        r'<source\b[^>]*\bsrc=["\']([^"\']+)["\']',
        r'<video\b[^>]*\bsrc=["\']([^"\']+)["\']',
        r'(?:file|video_url|videoUrl|hlsUrl)\s*[:=]\s*["\']([^"\']+)["\']',
        r'["\'](https?:\\?/\\?/[^"\'\s<>]+\.(?:m3u8|mp4)(?:\?[^"\'\s<>]*)?)["\']',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, source, re.I):
            candidate = html.unescape(match.group(1)).replace('\\/', '/')
            if '/preview.mp4' in candidate.lower():
                continue
            if re.search(r'\.(?:m3u8|mp4)(?:[?#]|$)', candidate, re.I):
                return absolute(candidate)
    return ''


VERSION_SUFFIXES = ('-uncensored-leak-chinese-subtitle',
                    '-chinese-subtitle-uncensored-leak',
                    '-uncensored-leak', '-chinese-subtitle')


def version_info(url):
    path = urlparse(url).path.rstrip('/')
    slug = path.rsplit('/', 1)[-1].lower()
    suffix = next((s for s in VERSION_SUFFIXES if slug.endswith(s)), '')
    code = slug[:-len(suffix)] if suffix else slug
    if not re.match(r'^(?:[a-z][a-z0-9]*-\d+|fc2(?:-ppv)?-\d+)$', code):
        return '', ''
    if 'uncensored-leak' in suffix and 'chinese-subtitle' in suffix:
        label = '无码中文字幕'
    elif 'uncensored-leak' in suffix:
        label = '无码流出'
    elif 'chinese-subtitle' in suffix:
        label = '中文字幕'
    else:
        label = '普通版'
    return code, label


def candidate_versions(url):
    """Probe same-code variants only; never manufacture them in the UI."""
    parsed = urlparse(url)
    code, _ = version_info(url)
    if not code:
        return [url]
    base = parsed.path.rsplit('/', 1)[0]
    paths = [base + '/' + code + suffix for suffix in
             ('', '-chinese-subtitle', '-uncensored-leak',
              '-uncensored-leak-chinese-subtitle',
              '-chinese-subtitle-uncensored-leak')]
    urls = [url] + [parsed._replace(path=path, query='', fragment='').geturl()
                    for path in paths]
    return list(dict.fromkeys(urls))


def parse_master_playlist(content, url):
    """Only label resolutions explicitly advertised by HLS master manifests."""
    lines = content.replace('\r', '').split('\n')
    variants = []
    for i, line in enumerate(lines):
        if not line.startswith('#EXT-X-STREAM-INF:'):
            continue
        match = re.search(r'RESOLUTION=(\d+)x(\d+)', line, re.I)
        if not match:
            continue
        for next_line in lines[i + 1:]:
            next_line = next_line.strip()
            if not next_line or next_line.startswith('#'):
                continue
            height = int(match.group(2))
            variants.append((str(height) + 'P', urljoin(url, next_line)))
            break
    return list(dict.fromkeys(variants))


def encode_play(code, media):
    return 'missavurl:' + quote(str(code or ''), safe='') + '|' + quote(media, safe='')


def decode_play(value):
    raw = value[len('missavurl:'):]
    if '|' in raw:
        code, media = raw.split('|', 1)
        return unquote(code), unquote(media)
    return '', unquote(raw)


def subtitle_code(url):
    code, _ = version_info(url)
    return code.upper()


def subtitle_items(data):
    """Read common Xunlei API response layouts, reject non-subtitle URLs."""
    if isinstance(data, list): return data
    if not isinstance(data, dict): return []
    for key in ('subtitles','subtitle','list','results','data'):
        value=data.get(key)
        if isinstance(value,list): return value
        if isinstance(value,dict):
            nested=subtitle_items(value)
            if nested:return nested
    return []


class Spider(BaseSpider):
    def init(self, extend=''):
        self.last = '未请求'
        self.last_url = ''
        self.cookie = ''
        self.last_preview = ''
        self.last_title = ''
        if isinstance(extend, dict):
            self.cookie = str(extend.get('cookie', '') or '')
        elif isinstance(extend, str) and extend.strip().startswith('{'):
            try:
                import json
                self.cookie = str(json.loads(extend).get('cookie', '') or '')
            except Exception:
                pass

    def getName(self):
        return 'MissAV Python'

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4)(?:[?#]|$)', str(url), re.I))

    def manualVideoCheck(self):
        return False

    def _request(self, path):
        url = absolute(path)
        self.last_url = url
        try:
            ua = self.net.getUserAgent() or UA
        except Exception:
            ua = UA
        headers = {
            'User-Agent': ua,
            'Referer': HOST + '/',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,*/*',
        }
        try:
            response = self.net.req(url, {
                'method': 'GET', 'timeout': 20000,
                'cookie': True, 'headers': headers
            })
            if isinstance(response, str):
                response = json.loads(response)
            if not isinstance(response, dict):
                raise TypeError('net.req 返回类型: ' + type(response).__name__)
            status = int(response.get('code', response.get('status', 0)) or 0)
            content = response.get('content', '') or ''
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='replace')
            else:
                content = str(content)
        except Exception as error:
            self.last = '请求异常: ' + str(error)
            return 0, '', False

        # Only a challenge signature in the returned page can confirm a
        # 200-response challenge. A 403 alone does not prove Cloudflare.
        signature = bool(re.search(
            r'<title[^>]*>\s*Just a moment\s*\.\.\.|'
            r'<form[^>]+(?:challenge-form|id=[\"\']challenge-form)|'
            r'<div[^>]+id=[\"\'](?:cf-challenge-running|challenge-stage)',
            content, re.I))
        challenge = status in (403, 429, 503)
        if status == 200 and signature:
            try:
                cards, _ = parse_videos(content)
                challenge = not bool(cards)
            except Exception:
                challenge = True
        title_match = re.search(r'<title[^>]*>([\s\S]*?)</title>', content, re.I)
        self.last_title = (
            html.unescape(re.sub(r'<[^>]+>', '', title_match.group(1))).strip()[:100]
            if title_match else '(无 title)'
        )
        self.last_preview = re.sub(
            r'\s+', ' ', re.sub(r'<[^>]+>', ' ', content[:3000])
        ).strip()[:180]
        self.last = 'HTTP {} | 长度 {} | 验证页 {} | title={} | {}'.format(
            status, len(content), '是' if challenge else '否', self.last_title, url)
        return status, content, challenge

    def _list(self, path, pg='1'):
        try:
            page = max(1, int(pg))
        except Exception:
            page = 1
        target = absolute(path)
        if page > 1:
            target += ('&' if '?' in target else '?') + 'page=' + str(page)
        status, source, challenge = self._request(target)
        if status != 200 or challenge or not source:
            return {'page': page, 'pagecount': page, 'limit': 20, 'total': page * 20,
                    'list': []}
        try:
            videos, parser = parse_videos(source)
        except Exception as error:
            self.last = 'HTML解析异常: ' + str(error)
            return {'page': page, 'pagecount': page, 'limit': 20, 'total': page * 20,
                    'list': []}
        # FongMi will not request the next search page when pagecount <= page.
        # MissAV search pages can omit a next link, even for nonempty results.
        # Advertise more pages while results exist; stop on empty or repeated pages.
        if page > 1 and videos:
            first_status, first_source, first_challenge = self._request(
                absolute(path))
            if first_status == 200 and not first_challenge:
                first_videos, _ = parse_videos(first_source)
                if first_videos and [v['vod_id'] for v in first_videos[:8]] == [
                        v['vod_id'] for v in videos[:8]]:
                    videos = []
        count = len(videos)
        return {'page': page, 'pagecount': page + 1 if count else page,
                'limit': count or 20,
                'total': (page + 1) * count if count else page * 20,
                'list': videos}

    def homeContent(self, filter):
        # Reuse the exact same native filter schema for all top-level categories.
        # The client controls whether filter UI is exposed inside folder navigation.
        return {'class': CATEGORIES,
                'filters': {item['type_id']: category_filter_config()
                            for item in CATEGORIES}}

    def homeVideoContent(self):
        return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        # Folder cards are routed to categoryContent using their vod_id.
        # Use the real entity URL as the category id to retain site pagination.
        entity_path = urlsplit(absolute(tid)).path.rstrip('/')
        if re.match(r'^(?:/dm\d+)?/cn/(?:actresses|genres|makers)/[^/]+$', entity_path, re.I) and not entity_path.endswith('/ranking'):
            selected = extend if isinstance(extend, dict) else {}
            sort = str(selected.get('sort', '') or '')
            work_filter = str(selected.get('work_filter', '') or '')
            result = self._list(append_options(tid, sort, [work_filter]), pg)
            # Hint only: clients that ignore filters in category responses
            # cannot be forced to show a native filter bar by a Spider.
            return result
        kind = special_kind(tid)
        if kind:
            try:
                page = max(1, int(pg))
            except Exception:
                page = 1
            url = absolute(tid)
            if page > 1:
                url += ('&' if '?' in url else '?') + 'page=' + str(page)
            status, body, blocked = self._request(url)
            items = parse_directory(body, kind) if status == 200 and not blocked else []
            # Ranking page is a single list; other directories have site pagination.
            more = bool(items) and urlsplit(absolute(tid)).path.rstrip('/') != '/cn/actresses/ranking'
            return {'list': items, 'page': page,
                    'pagecount': page + 1 if more else page,
                    'limit': len(items) or 20,
                    'total': (page + 1) * len(items) if more else len(items)}
        selected = extend if isinstance(extend, dict) else {}
        sort = str(selected.get('sort', '') or '')
        filters = [str(selected.get('work_filter', '') or '')]
        target = append_options(tid or '/cn', sort, filters)
        return self._list(target, pg)

    def searchContent(self, key, quick, pg='1'):
        keyword, sort, filters = parse_search_expression(key)
        if not keyword:
            return {'list': [], 'page': 1, 'pagecount': 1, 'limit': 20, 'total': 0}
        target = append_options('/cn/search/' + quote(keyword, safe=''), sort, filters)
        return self._search_aggregated(target, pg)

    def _search_aggregated(self, target, pg='1'):
        """Fetch up to three website pages per client page; return videos only."""
        try:
            client_page = max(1, int(pg))
        except (TypeError, ValueError):
            client_page = 1
        batch_size = 3
        first_site_page = (client_page - 1) * batch_size + 1
        items, seen = [], set()
        actresses, seen_actresses = [], set()
        completed_batch = False
        for site_page in range(first_site_page, first_site_page + batch_size):
            url = absolute(target)
            if site_page > 1:
                url += ('&' if '?' in url else '?') + 'page=' + str(site_page)
            status, body, blocked = self._request(url)
            if status != 200 or blocked or not body:
                break
            try:
                page_items, _ = parse_videos(body)
                page_actresses = parse_search_actresses(body)
            except Exception:
                break
            for actress in page_actresses:
                if actress['vod_id'] not in seen_actresses:
                    seen_actresses.add(actress['vod_id'])
                    actresses.append(actress)
            fresh = 0
            for item in page_items:
                if item['vod_id'] not in seen:
                    seen.add(item['vod_id'])
                    items.append(item)
                    fresh += 1
            if not page_items or fresh == 0:
                break
            if site_page == first_site_page + batch_size - 1:
                completed_batch = True
        # Put clickable actress portraits ahead of landscape video cards.
        # Keep search-page pagination driven by videos, not by repeated portraits.
        results = actresses + items
        n = len(results)
        return {'list': results, 'page': client_page,
                'pagecount': client_page + 1 if items and completed_batch else client_page,
                'limit': n or 20,
                'total': (client_page + 1) * n if n else client_page * 20}

    def _qualities(self, stream_url):
        # Some MissAV streams are direct 1080p/video.m3u8 and 720p/video.m3u8.
        # They are media playlists without EXT-X-STREAM-INF. Never discard them.
        hinted = stream_quality_hint(stream_url)
        if not re.search(r'\.m3u8(?:[?#]|$)', stream_url, re.I):
            return [(hinted or '原始画质', stream_url)]
        # Explicit CDN path gives a useful resolution label without a network roundtrip.
        if hinted:
            return [(hinted, stream_url)]
        status, manifest, challenge = self._request(stream_url)
        if status == 200 and not challenge and '#EXTM3U' in manifest[:200]:
            choices = parse_master_playlist(manifest, stream_url)
            if choices:
                return sorted(choices, key=lambda item: quality_rank(item[0]), reverse=True)
        return [('自动/原始', stream_url)]

def detail_related(source, current_url):
    """Extract actress profile links and video cards from the actual detail HTML.

    Never synthesize an actress URL: only use links present in the page.
    """
    actresses = []
    seen = set()
    pattern = r'<a\b([^>]*\bhref\s*=\s*[\"\']([^\"\']+)[\"\'][^>]*)>(.*?)</a\s*>'
    for m in re.finditer(pattern, source, re.I | re.S):
        url = absolute(html.unescape(m.group(2)))
        if not re.search(r'/(?:dm\d+/)?cn/actresses/[^/?#]+', urlsplit(url).path, re.I):
            continue
        if url in seen:
            continue
        body = m.group(3)
        name = re.sub(r'<[^>]*>', ' ', body)
        name = re.sub(r'\s+', ' ', html.unescape(name)).strip()
        img = re.search(r'<img\b[^>]*(?:data-src|src)=[\"\']([^\"\']+)', body, re.I | re.S)
        pic = absolute(img.group(1)) if img else ''
        if not name:
            name = unquote(urlsplit(url).path.rstrip('/').split('/')[-1]).replace('-', ' ')
        actresses.append({'name': name, 'url': url, 'pic': pic})
        seen.add(url)
    cards, _ = parse_videos(source)
    related = [v for v in cards if v['vod_id'] != current_url][:24]
    return actresses[:12], related


    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) else str(ids)
        if str(vid).startswith('missavdir:'):
            directory_url = unquote(str(vid)[len('missavdir:'):])
            if not directory_url.startswith(HOST + '/'):
                return {'list': []}
            status, body, blocked = self._request(directory_url)
            videos, _ = parse_videos(body) if status == 200 and not blocked else ([], None)
            title = unquote(urlsplit(directory_url).path.rstrip('/').split('/')[-1])
            # FongMi treats directory cards as video details. Present their first
            # page as a playable episode list, without changing the client.
            entries = ['{}$missavpage:{}'.format(
                re.sub(r'[$#]', ' ', v['vod_name']), quote(v['vod_id'], safe=''))
                for v in videos]
            return {'list': [{'vod_id': vid, 'vod_name': title,
                              'vod_content': '该目录第一页的影片；选择条目直接播放。',
                              'vod_play_from': '相关影片' if entries else '',
                              'vod_play_url': '#'.join(entries)}]}
        status, source, challenge = self._request(vid)
        if status != 200 or challenge:
            return {'list': [{'vod_id': vid, 'vod_name': '详情请求失败',
                              'vod_content': self.last}]}
        parser = PageParser()
        parser.feed(source)
        name = (' '.join(parser.title_text).strip() or
                parser.meta.get('og:title') or vid.rsplit('/', 1)[-1])
        code, _ = version_info(vid)
        actresses, related = detail_related(source, vid)
        # Discover real same-code variants via the verified /cn/search/<code> page.
        # Do not guess /dmNN/ paths: they can differ between versions.
        candidates = [vid]
        if code:
            search_status, search_html, search_blocked = self._request(
                '/cn/search/' + quote(code, safe=''))
            if search_status == 200 and not search_blocked:
                search_items, _ = parse_videos(search_html)
                for item in search_items:
                    url = item['vod_id']
                    other_code, _ = version_info(url)
                    if other_code == code and url not in candidates:
                        candidates.append(url)
        # Do not add speculative versions; the search results must contain them.
        groups = []
        seen_versions = set()
        for page in candidates:
            if page == vid:
                body = source
            else:
                status, body, blocked = self._request(page)
                if status != 200 or blocked:
                    continue
            found_code, label = version_info(page)
            if not found_code or (code and found_code != code) or label in seen_versions:
                continue
            # Sites can return a generic 200 fallback page for missing slugs.
            canonical = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', body, re.I)
            ogurl = re.search(r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)', body, re.I)
            actual = (canonical or ogurl)
            if actual:
                actual_code, actual_label = version_info(html.unescape(actual.group(1)))
                if actual_code != found_code or actual_label != label:
                    continue
            streams = extract_sources(body)
            if not streams:
                continue
            entries = []
            seen_urls = set()
            for stream_label, stream_url in streams:
                for quality, media_url in self._qualities(stream_url):
                    if media_url in seen_urls:
                        continue
                    seen_urls.add(media_url)
                    # Preserve every independently available URL, even if the CDN
                    # manifest is unavailable. Only use labels supported by the URL
                    # or by an HLS master playlist's RESOLUTION metadata.
                    entries.append((quality, stream_label, media_url))
            entries.sort(key=lambda item: quality_rank(item[0]), reverse=True)
            entries = ['{} · {}${}'.format(
                quality, stream_label, encode_play(found_code, media_url))
                for quality, stream_label, media_url in entries]
            if entries:
                groups.append((label, '#'.join(entries)))
                seen_versions.add(label)
        if related:
            recommended = ['{}$missavpage:{}'.format(
                re.sub(r'[$#]', ' ', item['vod_name'])[:70],
                quote(item['vod_id'], safe='')) for item in related]
            groups.append(('MissAV相关推荐', '#'.join(recommended)))
        actress_names = '、'.join(a['name'] for a in actresses)
        actress_info = ('\n女优：' + actress_names) if actress_names else ''
        if actresses:
            actress_info += '\n女优作品入口：女优一览 / 搜索女优姓名'
        return {'list': [{
            'vod_id': vid, 'vod_name': name,
            'vod_actor': actress_names,
            'vod_pic': absolute(parser.meta.get('og:image')) if parser.meta.get('og:image') else '',
            'vod_content': parser.meta.get('description', '') + actress_info +
                           ('\n可选版本：' + '、'.join(label for label, _ in groups)
                            if groups else '\n没有解析出有效播放线路'),
            'vod_play_from': '$$$'.join(label for label, _ in groups),
            'vod_play_url': '$$$'.join(items for _, items in groups)
        }]}

    def search_subtitles(self, code, video_duration=0):
        """Xunlei API: {code:0,data:[{url,name,ext,duration,languages}]}.

        duration is treated as milliseconds, consistent with the sample response.
        Empty languages are not interpreted as Chinese.
        """
        if not code:
            return []
        api = ('https://api-shoulei-ssl.xunlei.com/oracle/subtitle?name='
               + quote(code.upper(), safe=''))
        status, body, blocked = self._request(api)
        if status != 200 or not body or blocked:
            return []
        try:
            payload = json.loads(body)
            if isinstance(payload, dict) and payload.get('code') not in (None, 0):
                return []
            items = subtitle_items(payload)
        except (ValueError, TypeError):
            return []
        seen = set()
        candidates = []
        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get('url') or '').strip()
            if not url.startswith(('http://', 'https://')) or url in seen:
                continue
            ext = str(item.get('ext') or urlsplit(url).path.rsplit('.', 1)[-1]).lower().lstrip('.')
            if ext not in ('srt', 'ass', 'ssa', 'vtt'):
                continue
            seen.add(url)
            name = str(item.get('name') or code.upper() + '.' + ext)
            normalized = name.lower()
            if re.search(r'zh[-_]?cn|chs|简体|简中', normalized):
                score, lang = 3, 'zh-CN'
            elif re.search(r'zh|chi|中文|中字', normalized):
                score, lang = 2, 'zh-CN'
            else:
                score, lang = 0, 'und'
            try:
                duration = max(0, float(item.get('duration') or 0)) / 1000
            except (ValueError, TypeError):
                duration = 0
            delta = abs(duration - video_duration) if duration and video_duration else float('inf')
            candidates.append((score, delta, duration, {
                'url': url, 'name': name, 'lang': lang,
                'format': {'srt': 'application/x-subrip',
                           'ass': 'text/x-ssa', 'ssa': 'text/x-ssa',
                           'vtt': 'text/vtt'}[ext], 'flag': 0
            }))
        candidates.sort(key=lambda item: (-item[0], item[1], -item[2]))
        result = [item[3] for item in candidates[:15]]
        if result:
            result[0]['flag'] = 1
        self.subtitle_diagnostic = '{}：找到 {} 条字幕'.format(code.upper(), len(result))
        return result

    def playerContent(self, flag, id, vipFlags):
        target = str(id or '')
        code = ''
        if target.startswith('missavpage:'):
            page_url = unquote(target[len('missavpage:'):])
            if not page_url.startswith(HOST + '/'):
                return {'parse': 0, 'url': '', 'msg': '无效影片地址'}
            status, body, blocked = self._request(page_url)
            streams = extract_sources(body) if status == 200 and not blocked else []
            if not streams:
                return {'parse': 0, 'url': '', 'msg': '影片播放地址解析失败'}
            url = streams[0][1]
            code = subtitle_code(page_url)
        elif target.startswith('missavurl:'):
            code, url = decode_play(target)
        elif self.isVideoFormat(target):
            url = target
        else:
            return {'parse': 0, 'url': '', 'msg': '未知播放地址，请重新进入详情页'}
        if not re.match(r'^https?://', url, re.I):
            return {'parse': 0, 'url': '', 'msg': '无效播放地址'}
        subs = self.search_subtitles(code) if code else []
        return {'parse': 0, 'url': url,
                'header': {'User-Agent': UA, 'Referer': HOST + '/'},
                'subs': subs}

    def destroy(self):
        pass
