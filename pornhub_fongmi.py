# -*- coding: utf-8 -*-
"""Pornhub FongMi Python Spider v12 (real profile HTML, public pages only).
No login, CAPTCHA, DRM, geo restriction or payment bypass.
Requires FongMi Python Spider runtime (base.spider).
"""
import re
import json
import html
import urllib.request
import urllib.parse
import urllib.error
import time
from html.parser import HTMLParser
from base.spider import Spider as BaseSpider

HOST = 'https://cn.pornhub.com'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.8',
    'Referer': HOST + '/',
}
CATEGORIES = [
    {'type_name': '色情明星', 'type_id': 'pornstars'},
    {'type_name': '最新视频', 'type_id': '/video?o=cm'},
    {'type_name': '热门视频', 'type_id': '/video?o=ht'},
    {'type_name': '最多观看', 'type_id': '/video?o=mv'},
    {'type_name': '评分最高', 'type_id': '/video?o=tr'},
]

def clean(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', str(value or '')))).strip()

def absolute(url):
    return urllib.parse.urljoin(HOST, html.unescape(url or ''))

def get(url):
    req = urllib.request.Request(absolute(url), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=18) as resp:
        charset = resp.headers.get_content_charset() or 'utf-8'
        return resp.read().decode(charset, errors='replace')

def attrs_dict(attrs):
    return dict(attrs)

def pick_thumbnail(attrs):
    """Prefer the card still image; support non-lazy images on top cards."""
    for key in ('data-mediumthumb', 'data-image', 'data-thumb_url', 'data-original', 'data-src', 'src'):
        raw = html.unescape(attrs.get(key) or '').strip()
        if not raw or raw in ('#', '/'):
            continue
        low = raw.lower()
        if low.startswith(('data:', 'blob:', 'javascript:')):
            continue
        if any(x in low for x in ('placeholder', 'blank.gif', 'loading.gif', 'pixel.gif')):
            continue
        if raw.startswith(('http://', 'https://', '//', '/')):
            return absolute(raw)
    return ''


def pick_performer_image(attrs):
    """Keep the original fallback strategy for performer portraits."""
    for key in ('data-mediumthumb', 'data-image', 'data-thumb_url',
                'data-original', 'data-src', 'src', 'data-srcset', 'srcset'):
        raw = html.unescape(attrs.get(key) or '').strip()
        if key.endswith('srcset') and raw:
            raw = raw.split(',')[-1].strip().split(' ')[0]
        if not raw:
            continue
        low = raw.lower()
        if (low.startswith(('data:', 'blob:', 'javascript:')) or
            any(x in low for x in ('placeholder', 'blank.gif', 'loading.gif', 'pixel.gif')) or
            (re.search(r'\.(?:mp4|webm)(?:[/?#]|$)', low) and not ('/plain/' in low and ('/vts:' in low or '/rs:fit:' in low))) or raw in ('#', '/')):
            continue
        if raw.startswith(('http://', 'https://', '//', '/')):
            return absolute(raw)
    return ''


def picture_from_html(source):
    """Extract a still image from the video page when a list card lacks one."""
    pic = match_meta(source, 'og:image')
    if pic:
        return absolute(pic)
    ld = ld_video(source)
    pic = ld.get('thumbnailUrl') or ''
    if isinstance(pic, list):
        pic = next((x for x in pic if isinstance(x, str)), '')
    return absolute(pic) if isinstance(pic, str) and pic else ''


class CardParser(HTMLParser):
    """Extract actual video cards, including lazy images outside anchor tags."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards = []
        self.li_depth = 0
        self.current = None
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == 'li':
            if self.current is None:
                self.current = {'href': '', 'title': '', 'image': '', 'text': []}
                self.li_depth = 1
            else:
                self.li_depth += 1
        if self.current is None:
            return
        if tag == 'a':
            href = d.get('href', '')
            if 'view_video.php' in href and 'viewkey=' in href:
                self.current['href'] = self.current['href'] or href
                self.current['title'] = self.current['title'] or d.get('title', '')
                self.anchor = True
        elif tag == 'img':
            pic = pick_thumbnail(d)
            if pic and not self.current['image']:
                self.current['image'] = pic
            self.current['title'] = self.current['title'] or d.get('alt', '')

    def handle_data(self, data):
        if self.current is not None and self.anchor:
            self.current['text'].append(data)

    def handle_endtag(self, tag):
        if tag == 'a':
            self.anchor = None
        if tag == 'li' and self.current is not None:
            self.li_depth -= 1
            if self.li_depth <= 0:
                if self.current['href']:
                    self.cards.append(self.current)
                self.current = None

def parse_cards(source):
    p = CardParser()
    p.feed(source)
    result, seen = [], set()
    for card in p.cards:
        url = absolute(card['href'])
        key = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get('viewkey', [''])[0]
        if not key or key in seen:
            continue
        title = clean(card['title']) or clean(' '.join(card['text'])) or key
        seen.add(key)
        result.append({'vod_id': url, 'vod_name': title,
                       'vod_pic': card['image'], 'vod_remarks': '',
                       'style': {'type': 'rect', 'ratio': 1.78}})
    return result


def parse_profile_videos(source):
    """Select actual profile listing containers and parse all their cards."""
    target_ids = ('mostRecentVideosSection', 'uploadedVideosSection', 'videoSearchResult', 'videosUploadedSection',
                  'modelMostRecentVideosSection', 'pornstarsVideosSection')
    class Region(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.capture = False
            self.root_tag = ''
            self.depth = 0
            self.parts = []
            self.regions = []
        def handle_starttag(self, tag, attrs):
            d = dict(attrs)
            if not self.capture and d.get('id') in target_ids:
                self.capture, self.root_tag, self.depth = True, tag, 1
                self.parts = [self.get_starttag_text()]
                return
            if self.capture:
                self.parts.append(self.get_starttag_text())
                if tag == self.root_tag:
                    self.depth += 1
        def handle_startendtag(self, tag, attrs):
            if self.capture:
                self.parts.append(self.get_starttag_text())
        def handle_endtag(self, tag):
            if self.capture:
                self.parts.append('</%s>' % tag)
                if tag == self.root_tag:
                    self.depth -= 1
                    if self.depth == 0:
                        self.regions.append(''.join(self.parts))
                        self.capture = False
        def handle_data(self, data):
            if self.capture:
                self.parts.append(html.escape(data))
        def handle_entityref(self, name):
            if self.capture: self.parts.append('&'+name+';')
        def handle_charref(self, name):
            if self.capture: self.parts.append('&#'+name+';')
    region = Region()
    region.feed(source)
    # Preserve page order and remove duplicate viewkeys across all relevant grids.
    combined = []
    seen = set()
    for section in region.regions[:1]:
        for video in parse_cards(section):
            if video['vod_id'] not in seen:
                seen.add(video['vod_id'])
                combined.append(video)
    return combined

class PornstarParser(HTMLParser):
    """Read ranked performer cards only from ul#popularPornstars."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_list = False
        self.list_depth = 0
        self.card = None
        self.card_depth = 0
        self.capture_name = False
        self.name_depth = 0
        self.items = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        classes = (d.get('class') or '').split()
        if tag == 'ul' and d.get('id') == 'popularPornstars':
            self.in_list, self.list_depth = True, 1
            return
        if not self.in_list:
            return
        if tag == 'ul':
            self.list_depth += 1
        if tag == 'li' and 'performerCard' in classes and self.card is None:
            self.card = {'href': '', 'name': '', 'image': '', 'rank': ''}
            self.card_depth = 1
        elif tag == 'li' and self.card is not None:
            self.card_depth += 1
        if self.card is None:
            return
        if tag == 'a':
            href = d.get('href', '')
            path = urllib.parse.urlsplit(absolute(href)).path.rstrip('/')
            if re.fullmatch(r'/(?:pornstar|model)/[^/]+', path, re.I):
                if not self.card['href']:
                    self.card['href'] = href
                if 'title' in classes:
                    self.capture_name = True
                    self.name_depth = 1
        elif tag == 'img':
            self.card['image'] = self.card['image'] or pick_performer_image(d)
            self.card['name'] = self.card['name'] or d.get('alt', '')
        elif tag == 'span' and 'rank_number' in classes:
            self._rank_capture = True
        if self.capture_name and tag not in ('a',):
            self.name_depth += 1

    def handle_data(self, data):
        if self.card is not None:
            if getattr(self, '_rank_capture', False):
                value = data.strip()
                if value.isdigit():
                    self.card['rank'] = value
            if self.capture_name and not self.card['name']:
                self.card['name'] = data.strip()

    def handle_endtag(self, tag):
        if not self.in_list:
            return
        if tag == 'span':
            self._rank_capture = False
        if tag == 'a':
            self.capture_name = False
        if tag == 'li' and self.card is not None:
            self.card_depth -= 1
            if self.card_depth == 0:
                if self.card['href']:
                    self.items.append(self.card)
                self.card = None
        if tag == 'ul':
            self.list_depth -= 1
            if self.list_depth == 0:
                self.in_list = False


def parse_pornstars(source):
    parser = PornstarParser()
    parser.feed(source)
    result, seen = [], set()
    for item in parser.items:
        url = absolute(item['href'])
        if url in seen:
            continue
        name = clean(item['name']) or urllib.parse.unquote(url.rstrip('/').split('/')[-1]).replace('-', ' ')
        seen.add(url)
        result.append({'vod_id': 'pornstar:' + url, 'vod_name': name,
                       'vod_pic': item['image'],
                       'vod_remarks': ('排名 #' + item['rank']) if item['rank'] else '明星目录',
                       'vod_tag': 'folder', 'style': {'type': 'oval'}})
    return result

def ld_video(source):
    for raw in re.findall(r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', source, re.I | re.S):
        try:
            doc = json.loads(html.unescape(raw))
            items = doc if isinstance(doc, list) else [doc]
            for item in items:
                if isinstance(item, dict) and item.get('@type') == 'VideoObject':
                    return item
        except (ValueError, TypeError):
            pass
    return {}

def match_meta(source, name):
    for tag in re.findall(r'<meta\b[^>]*>', source, re.I):
        props = dict((k.lower(), html.unescape(v)) for k, v in
                     re.findall(r'([\w:-]+)\s*=\s*["\']([^"\']*)["\']', tag))
        if props.get('property') == name or props.get('name') == name:
            return props.get('content', '')
    return ''

def player_config(source):
    """Only read the video's own player configuration, never ad/preroll fields."""
    match = re.search(r'var\s+flashvars_\d+\s*=\s*(\{.*?\})\s*;', source, re.S)
    if not match:
        return {}
    try:
        config = json.loads(match.group(1))
        if str(config.get('video_unavailable', 'false')).lower() == 'true':
            return {}
        return config
    except (ValueError, TypeError):
        return {}


def media_definitions(source):
    """Expose HLS resolutions only. Do not treat get_media MP4 as verified."""
    config = player_config(source)
    result, seen = [], set()
    for entry in config.get('mediaDefinitions', []):
        if not isinstance(entry, dict) or str(entry.get('format', '')).lower() != 'hls':
            continue
        url = entry.get('videoUrl', '')
        if not isinstance(url, str):
            continue
        url = html.unescape(url.replace('\\/', '/'))
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != 'https' or not parts.path.lower().endswith('.m3u8'):
            continue
        quality = str(entry.get('quality') or entry.get('height') or '').strip()
        if not quality.isdigit() or (quality, url) in seen:
            continue
        seen.add((quality, url))
        result.append((quality, url))
    return result


def expected_video_duration(source):
    config = player_config(source)
    try:
        value = float(config.get('video_duration', 0))
        if value > 0:
            return value
    except (ValueError, TypeError):
        pass
    info = ld_video(source)
    value = str(info.get('duration') or '')
    m = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?', value, re.I)
    if m:
        return float(m.group(1) or 0) * 3600 + float(m.group(2) or 0) * 60 + float(m.group(3) or 0)
    return 0


def fetch_playlist(url, referer):
    headers = {**HEADERS, 'Referer': referer,
               'Origin': urllib.parse.urlsplit(referer).scheme + '://' + urllib.parse.urlsplit(referer).netloc,
               'Accept': 'application/vnd.apple.mpegurl, application/x-mpegURL, */*'}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            mime = (response.headers.get('Content-Type') or '').lower()
            raw = response.read(1024 * 1024)
        content = raw.decode('utf-8-sig', 'replace')
        if not content.lstrip().startswith('#EXTM3U') or 'text/html' in mime:
            return ''
        return content
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError):
        return ''


def hls_duration(url, referer, depth=0):
    """Return duration of a media playlist; None means unverified."""
    if depth > 3:
        return None
    content = fetch_playlist(url, referer)
    if not content:
        return None
    segments = re.findall(r'^#EXTINF:\s*([0-9]+(?:\.[0-9]+)?)', content, re.M)
    if segments:
        # A live/partial playlist is not proof of the complete movie.
        if '#EXT-X-ENDLIST' not in content:
            return None
        return sum(float(x) for x in segments)
    if '#EXT-X-STREAM-INF' not in content:
        return None
    lines = content.splitlines()
    children = []
    for i, line in enumerate(lines):
        if not line.startswith('#EXT-X-STREAM-INF'):
            continue
        for candidate in lines[i + 1:]:
            candidate = candidate.strip()
            if not candidate:
                continue
            if not candidate.startswith('#'):
                children.append(urllib.parse.urljoin(url, candidate))
            break
    for child in children[:4]:
        duration = hls_duration(child, referer, depth + 1)
        if duration is not None:
            return duration
    return None


def check_full_hls(url, referer, expected):
    """Reject short ads/previews; fail closed if full duration cannot be verified."""
    duration = hls_duration(url, referer)
    if duration is None or duration < 30:
        return False
    if expected >= 60:
        # Permit minor rounding differences, not a 15-second preview.
        return duration >= expected * 0.85
    return duration >= max(20, expected * 0.7)


def make_play_id(page_url, quality):
    # Store a stable page URL and quality, never an expiring signed CDN URL.
    return urllib.parse.quote(json.dumps({'page': page_url, 'quality': quality},
                                         ensure_ascii=False), safe='')

class Spider(BaseSpider):
    def init(self, extend=''):
        pass
    def getName(self):
        return 'Pornhub v13（真实40条列表解析）'
    def isVideoFormat(self, url):
        return bool(re.search(r'\.(?:mp4|m3u8)(?:[?#]|$)', str(url), re.I))
    def manualVideoCheck(self):
        return False
    def homeContent(self, filter=False):
        return {'class': CATEGORIES, 'filters': {}}
    def homeVideoContent(self):
        try:
            return {'list': parse_cards(get('/video'))}
        except Exception:
            return {'list': []}
    def categoryContent(self, tid, pg, filter=False, extend=None):
        try:
            pg = max(1, int(pg))
            if tid == 'pornstars':
                path = '/pornstars' + ('?page=' + str(pg) if pg > 1 else '')
                stars = parse_pornstars(get(path))
                return {'list': stars, 'page': pg,
                        'pagecount': pg + 1 if stars else pg,
                        'limit': len(stars), 'total': 999999 if stars else 0}
            if str(tid).startswith('pornstar:'):
                profile = str(tid)[len('pornstar:'):]
                parts = urllib.parse.urlsplit(absolute(profile))
                path = parts.path.rstrip('/') + '/videos'
                url = absolute(path) + ('?page=' + str(pg) if pg > 1 else '')
                source = get(url)
                videos = parse_profile_videos(source)
                return {'list': videos, 'page': pg,
                        'pagecount': pg + 1 if videos else pg,
                        'limit': len(videos), 'total': 999999 if videos else 0}
            parts = urllib.parse.urlsplit(absolute(tid))
            qs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
            qs = [(k, v) for k, v in qs if k != 'page']
            if pg > 1:
                qs.append(('page', str(pg)))
            url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path,
                                           urllib.parse.urlencode(qs), ''))
            videos = parse_cards(get(url))
            return {'list': videos, 'page': pg, 'pagecount': pg + 1 if videos else pg,
                    'limit': len(videos), 'total': 999999 if videos else 0}
        except Exception:
            return {'list': [], 'page': int(pg or 1), 'pagecount': int(pg or 1), 'limit': 0, 'total': 0}
    def searchContent(self, key, quick=False, pg='1'):
        path = '/video/search?search=' + urllib.parse.quote(str(key))
        return self.categoryContent(path, pg, False, {})
    def detailContent(self, ids):
        if str(ids[0]).startswith('pornstar:'):
            profile = str(ids[0])[len('pornstar:'):]
            path = urllib.parse.urlsplit(absolute(profile)).path.rstrip('/') + '/videos'
            try:
                videos = parse_profile_videos(get(path))
                if not videos:
                    videos = parse_profile_videos(get(profile))
                if not videos:
                    return {'list': []}
                episodes = []
                for video in videos:
                    page = video['vod_id']
                    episodes.append(video['vod_name'].replace('$', ' ').replace('#', ' ') +
                                    '$' + make_play_id(page, 'auto'))
                return {'list': [{
                    'vod_id': ids[0], 'vod_name': '明星视频（点击选集播放）',
                    'vod_pic': videos[0].get('vod_pic', ''),
                    'vod_content': '当前页面共 %d 个视频；点击选集播放。' % len(videos),
                    'vod_play_from': '明星视频',
                    'vod_play_url': '#'.join(episodes)
                }]}
            except Exception:
                return {'list': []}
        url = absolute(ids[0])
        try:
            source = get(url)
            ld = ld_video(source)
            title = clean(ld.get('name')) or match_meta(source, 'og:title') or '视频'
            pic = ld.get('thumbnailUrl') or match_meta(source, 'og:image') or ''
            if isinstance(pic, list):
                pic = pic[0] if pic else ''
            pic = absolute(pic) if pic else ''
            desc = clean(ld.get('description')) or match_meta(source, 'og:description')
            media = media_definitions(source)
            urls = [f'{quality}P${make_play_id(url, quality)}' for quality, _ in media]
            if not urls:
                urls = ['网页地址$' + urllib.parse.quote(url, safe='')]
            return {'list': [{'vod_id': url, 'vod_name': title, 'vod_pic': pic,
                              'vod_content': desc, 'vod_play_from': '实时HLS' if media else '网页回退',
                              'vod_play_url': '#'.join(urls)}]}
        except Exception:
            return {'list': []}
    def playerContent(self, flag, id, vipFlags=None):
        value = urllib.parse.unquote(str(id))
        try:
            data = json.loads(value)
            page = data.get('page', '')
            quality = str(data.get('quality', '')).replace('P', '').strip()
            if not page or 'view_video.php' not in page:
                return {'parse': 1, 'url': page or value}
            source = get(page)
            expected = expected_video_duration(source)
            choices = media_definitions(source)
            # Never silently switch quality or use a preview/advertisement MP4.
            if quality.isdigit():
                choices = [(q, u) for q, u in choices if q == quality]
            else:
                choices.sort(key=lambda x: int(x[0]), reverse=True)
            for q, media_url in choices:
                if check_full_hls(media_url, page, expected):
                    return {'parse': 0, 'url': media_url, 'header': {
                        'User-Agent': HEADERS['User-Agent'],
                        'Referer': page,
                        'Origin': urllib.parse.urlsplit(page).scheme + '://' + urllib.parse.urlsplit(page).netloc,
                    }}
            # No verified full stream: return webpage rather than a wrong short clip.
            return {'parse': 1, 'url': page}
        except (ValueError, TypeError):
            return {'parse': 1, 'url': value}
        except Exception:
            return {'parse': 1, 'url': value if value.startswith('http') else HOST + '/'}
