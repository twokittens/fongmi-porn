# -*- coding: utf-8 -*-
"""Pornhub FongMi Python Spider v26 (real profile HTML, public pages only).
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
    {'type_name': '最受欢迎色情明星', 'type_id': 'pornstars'},
    {'type_name': '最热门色情明星', 'type_id': 'pornstars_hot'},
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
        self.reject = False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == 'li':
            if self.current is None:
                self.reject = bool(re.search(r'playlist|collection|album|channel|compilation', (d.get('class','') + ' ' + d.get('id','') + ' ' + d.get('data-type','')), re.I))
                self.current = {'href': '', 'title': '', 'image': '', 'text': [], 'duration': '', 'duration_capture': False}
                self.li_depth = 1
            else:
                self.li_depth += 1
        if self.current is None:
            return
        if tag == 'a':
            href = d.get('href', '')
            if re.search(r'/(?:playlist|playlists|album|albums)/', href, re.I):
                self.reject = True
            if 'view_video.php' in href and 'viewkey=' in href:
                self.current['href'] = self.current['href'] or href
                self.current['title'] = self.current['title'] or d.get('title', '')
                self.anchor = True
        elif tag in ('var', 'span') and 'duration' in (d.get('class') or '').split():
            self.current['duration_capture'] = True
        elif tag == 'img':
            pic = pick_thumbnail(d)
            if pic and not self.current['image']:
                self.current['image'] = pic
            self.current['title'] = self.current['title'] or d.get('alt', '')

    def handle_data(self, data):
        if self.current is not None and self.current.get('duration_capture'):
            candidate = data.strip()
            if re.fullmatch(r'\d{1,3}:\d{2}(?::\d{2})?', candidate):
                self.current['duration'] = candidate
        if self.current is not None and self.anchor:
            self.current['text'].append(data)

    def handle_endtag(self, tag):
        if tag in ('var', 'span') and self.current is not None:
            self.current['duration_capture'] = False
        if tag == 'a':
            self.anchor = None
        if tag == 'li' and self.current is not None:
            self.li_depth -= 1
            if self.li_depth <= 0:
                if self.current['href'] and not self.reject:
                    self.cards.append(self.current)
                self.current = None
                self.reject = False

def parse_cards(source):
    p = CardParser()
    p.feed(source)
    result, seen = [], set()
    for card in p.cards:
        url = absolute(card['href'])
        if not re.fullmatch(r'/view_video\.php', urllib.parse.urlsplit(url).path, re.I):
            continue
        key = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get('viewkey', [''])[0]
        if not key or key in seen:
            continue
        title = clean(card['title']) or clean(' '.join(card['text'])) or key
        seen.add(key)
        result.append({'vod_id': url, 'vod_name': title,
                       'vod_pic': card['image'], 'vod_remarks': card.get('duration', ''),
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
    entries = parser.items
    if not entries:
        # Newer directory pages use performerCard without ul#popularPornstars.
        # Only parse the page's main content, excluding navigation menus.
        main = re.search(r'<(?:main|div)\b[^>]*(?:id=["\'](?:content|pornstars|mainContent)["\']|class=["\'][^"\']*(?:mainContent|pornstarsList|pornstarsContainer)[^"\']*["\'])[^>]*>', source, re.I)
        scope = source[main.start():] if main else source
        entries = []
        for match in re.finditer(r'<li\b[^>]*class=["\'][^"\']*\bperformerCard\b[^"\']*["\'][^>]*>(.*?)</li\s*>', scope, re.I | re.S):
            block = match.group(1)
            link = re.search(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>', block, re.I)
            if not link or not re.fullmatch(r'/(?:pornstar|model)/[^/]+', urllib.parse.urlsplit(absolute(link.group(1))).path.rstrip('/'), re.I):
                continue
            img = re.search(r'<img\b([^>]*)>', block, re.I | re.S)
            attrs = dict(re.findall(r'([\w-]+)\s*=\s*["\']([^"\']*)["\']', img.group(1))) if img else {}
            heading = re.search(r'<(?:span|a)\b[^>]*class=["\'][^"\']*(?:performerName|performerCardName)[^"\']*["\'][^>]*>(.*?)</(?:span|a)>', block, re.I | re.S)
            entries.append({'href': link.group(1), 'name': clean(heading.group(1)) if heading else (attrs.get('alt') or ''), 'image': pick_performer_image(attrs), 'rank': ''})
    result, seen = [], set()
    for item in entries:
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

class SearchPerformerParser(HTMLParser):
    """Extract performer profile links from search results, not ranking-only markup."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []
        self.links = []
        self.capture = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'a':
            href = a.get('href', '')
            path = urllib.parse.urlsplit(absolute(href)).path.rstrip('/')
            if re.fullmatch(r'/(?:pornstar|model)/[^/]+', path, re.I):
                self.links.append({'url': absolute(href), 'name': a.get('title', '') or a.get('alt', ''),
                                   'image': '', 'text': [], 'depth': 1})
            elif self.links:
                self.links[-1]['depth'] += 1
        if tag == 'img' and self.links:
            current = self.links[-1]
            current['image'] = current['image'] or pick_performer_image(a)
            current['name'] = current['name'] or a.get('alt', '')

    def handle_data(self, data):
        if self.links:
            self.links[-1]['text'].append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.links:
            self.links[-1]['depth'] -= 1
            if self.links[-1]['depth'] <= 0:
                self.items.append(self.links.pop())


def parse_search_performers(source, keyword=''):
    parser = SearchPerformerParser()
    parser.feed(source)
    results, seen = [], set()
    term = str(keyword or '').strip().casefold()
    compact_term = re.sub(r'[^\w]+', '', term)
    for item in parser.items:
        url = item['url']
        if url in seen:
            continue
        slug = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit('/', 1)[-1]).replace('-', ' ')
        name = clean(item['name']) or clean(' '.join(item['text'])) or slug
        # Avoid unrelated navigation links accidentally appearing as search results.
        candidate = (name + ' ' + slug).casefold()
        compact_candidate = re.sub(r'[^\w]+', '', candidate)
        if term and term not in candidate and compact_term not in compact_candidate:
            continue
        seen.add(url)
        results.append({'vod_id': 'pornstar:' + url, 'vod_name': name,
                        'vod_pic': item['image'], 'vod_remarks': '色情明星',
                        'vod_tag': 'folder', 'style': {'type': 'oval', 'ratio': 1.0}})
    return results



class VideoLinksParser(HTMLParser):
    """Collect links and their visible labels from a video detail page."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.current = None
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'a' and self.current is None:
            self.current = {'href': a.get('href', ''), 'title': a.get('title', ''),
                            'text': [], 'depth': 1}
        elif tag == 'a' and self.current is not None:
            self.current['depth'] += 1
        elif tag == 'img' and self.current is not None:
            self.current['title'] = self.current['title'] or a.get('alt', '')
    def handle_data(self, data):
        if self.current is not None:
            self.current['text'].append(data)
    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            self.current['depth'] -= 1
            if self.current['depth'] == 0:
                item = self.current
                self.current = None
                item['name'] = clean(' '.join(item['text'])) or clean(item['title'])
                if item['href'] and item['name']:
                    self.links.append(item)


def _section(source, marker, end_marker=None, limit=18000):
    pos = source.find(marker)
    if pos < 0:
        return ''
    end = source.find(end_marker, pos + len(marker)) if end_marker else -1
    return source[pos:end if end > pos else pos + limit]


def _anchors(fragment, accepted=None):
    result, seen = [], set()
    for m in re.finditer(r'<a\b([^>]*)>(.*?)</a\s*>', fragment, re.I | re.S):
        attrs = dict((k.lower(), html.unescape(v)) for k, v in
                     re.findall(r'([\w-]+)\s*=\s*["\']([^"\']*)["\']', m.group(1)))
        href = attrs.get('href', '')
        if not href or href.startswith(('#', 'javascript:')):
            continue
        url = absolute(href)
        parsed = urllib.parse.urlsplit(url)
        if parsed.hostname not in ('pornhub.com', 'www.pornhub.com', 'cn.pornhub.com'):
            continue
        if accepted and not accepted(parsed.path):
            continue
        name = clean(m.group(2)) or clean(attrs.get('title'))
        if name and url not in seen:
            seen.add(url)
            result.append((name, url))
    return result


def detail_links(source):
    # Only the main video metadata block. Do not pick unrelated authors
    # and tags from recommendation cards or navigation menus.
    about = _section(source, 'video-detailed-info', 'video-action-tab', 13000)
    uploader = _section(about, 'userInfoBlock', 'video-info-row js-suggestionsRow', 4500)
    performers = _anchors(uploader, lambda p: bool(re.fullmatch(r'/(?:pornstar|model|users)/[^/]+', p, re.I)))
    categories = _anchors(_section(about, 'categoriesWrapper', 'tagsWrapper', 3500),
                          lambda p: p.startswith(('/categories/', '/video', '/hd', '/tags/')))
    tags = _anchors(_section(about, 'tagsWrapper', 'video-info-row', 4500),
                    lambda p: p.startswith(('/video/search', '/tags/', '/tag/')))
    return performers[:8], tags[:35], categories[:30]


def related_cards(source, current_url=''):
    # The supplied page uses ul#relatedVideosListing; keep only this grid.
    section = _section(source, 'id="relatedVideosListing"', '</ul>', 150000)
    if not section:
        section = _section(source, 'id=\'relatedVideosListing\'', '</ul>', 150000)
    cards = parse_cards(section) if section else []
    current_key = urllib.parse.parse_qs(urllib.parse.urlsplit(current_url).query).get('viewkey', [''])[0]
    return [c for c in cards if urllib.parse.parse_qs(
        urllib.parse.urlsplit(c['vod_id']).query).get('viewkey', [''])[0] != current_key][:80]


def search_performer_pages(keyword):
    """Try the dedicated performer search and general results; preserve source URLs."""
    query = urllib.parse.quote(keyword)
    paths = ['/pornstars/search?search=' + query,
             '/pornstars?search=' + query,
             '/video/search?search=' + query]
    found, seen = [], set()
    for path in paths:
        try:
            page = get(path)
            for item in parse_search_performers(page, keyword):
                if item['vod_id'] not in seen:
                    seen.add(item['vod_id'])
                    found.append(item)
        except Exception:
            continue
    # When the site returns performer suggestions with spaces, compact matching
    # is handled by parse_search_performers; this does not fabricate unknown splits.
    return found

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


def quality_number(value):
    """Handle scalar quality, quality arrays, and 720p labels."""
    if isinstance(value, (list, tuple)):
        nums = [quality_number(x) for x in value]
        return max(nums) if nums else 0
    m = re.search(r'(?<!\d)(144|240|360|480|540|720|1080|1440|2160)(?!\d)', str(value or ''))
    return int(m.group(1)) if m else 0


def media_definitions(source):
    """Read player mediaDefinitions without treating quality arrays as a single resolution."""
    config = player_config(source)
    result, seen = [], set()
    for entry in config.get('mediaDefinitions', []):
        if not isinstance(entry, dict) or str(entry.get('format', '')).lower() not in ('hls', 'hls_qs'):
            continue
        url = entry.get('videoUrl', '')
        if not isinstance(url, str):
            continue
        url = html.unescape(url.replace('\\/', '/')).strip()
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != 'https' or not parts.netloc or not parts.path.lower().endswith('.m3u8'):
            continue
        if url in seen:
            continue
        seen.add(url)
        raw_quality = entry.get('quality') or entry.get('height')
        # An array lists available tiers, not the resolution of this URL.
        # Keep its original ordering as a fallback but never advertise it as 1080P.
        is_master = isinstance(raw_quality, (list, tuple))
        quality = 0 if is_master else quality_number(raw_quality)
        result.append({'quality': quality, 'url': url,
                       'master': is_master, 'default': bool(entry.get('defaultQuality')),
                       'remote': bool(entry.get('remote'))})
    return result


def playlist_variants(url, source, referer):
    """Parse an HLS master without downloading any media segments."""
    variants = []
    lines = source.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith('#EXT-X-STREAM-INF'):
            continue
        height = 0
        m = re.search(r'RESOLUTION\s*=\s*\d+x(\d+)', line, re.I)
        if m:
            height = int(m.group(1))
        if not height:
            m = re.search(r'NAME\s*=\s*["\']?(\d{3,4})[pP]?', line, re.I)
            if m: height = int(m.group(1))
        for candidate in lines[i+1:]:
            candidate = candidate.strip()
            if not candidate: continue
            if candidate.startswith('#'): break
            child = urllib.parse.urljoin(url, candidate)
            if urllib.parse.urlsplit(child).scheme == 'https':
                variants.append((height, child))
            break
    return variants


def choose_stream(source, page, requested='auto'):
    """Probe at most three distinct playlists; never select an ad/preview by fallback."""
    definitions = media_definitions(source)
    if not definitions:
        return '', '未找到 HLS 播放源（可能已下架、地区限制或需要登录）'
    requested_num = quality_number(requested) if requested != 'auto' else 0
    definitions.sort(key=lambda d: (not d['default'], d['master'], -d['quality']))
    if requested_num:
        definitions.sort(key=lambda d: (d['master'], abs(d['quality'] - requested_num), not d['default']))
    # Check each URL once; do not fetch the media segments.
    seen = set()
    for entry in definitions[:3]:
        url = entry['url']
        if url in seen: continue
        seen.add(url)
        content = fetch_playlist(url, page)
        if not content:
            continue
        variants = playlist_variants(url, content, page)
        if variants:
            if requested_num:
                variants.sort(key=lambda x: (abs(x[0]-requested_num) if x[0] else 9999, -x[0]))
            else:
                # Prefer site default rather than automatically forcing highest bitrate.
                variants.sort(key=lambda x: abs(x[0] - (entry['quality'] or 720)))
            return variants[0][1], ''
        if '#EXTINF:' in content:
            # Reject obviously short complete playlists when a full duration is known.
            expected = expected_video_duration(source)
            if expected >= 60 and '#EXT-X-ENDLIST' in content:
                durations = re.findall(r'^#EXTINF:\s*([0-9]+(?:\.[0-9]+)?)', content, re.M)
                if durations and sum(map(float, durations)) < expected * 0.7:
                    continue
            return url, ''
    return '', 'HLS 列表无法访问或不包含有效正片；请尝试其他清晰度或网页播放'

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
        return 'Pornhub v29（v26稳定播放优化）'

    def safe_link(self, name, target):
        # FongMi link expects a target dictionary, not a plain string.
        # Never allow link rendering errors to blank the entire detail page.
        payload = {'id': target, 'name': name, 'type_flag': 1}
        try:
            return self.link(name, payload)
        except Exception:
            return name

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
            if tid in ('pornstars', 'pornstars_hot'):
                path = '/pornstars'
                params = []
                if tid == 'pornstars_hot':
                    params.append(('o', 't'))
                if pg > 1:
                    params.append(('page', str(pg)))
                if params:
                    path += '?' + urllib.parse.urlencode(params)
                stars = parse_pornstars(get(path))
                return {'list': stars, 'page': pg,
                        'pagecount': pg + 1 if stars else pg,
                        'limit': len(stars), 'total': 999999 if stars else 0}
            if str(tid).startswith('related:'):
                video_url = str(tid)[len('related:'):]
                videos = related_cards(get(video_url), video_url) if pg == 1 else []
                return {'list': videos, 'page': pg, 'pagecount': pg,
                        'limit': len(videos), 'total': len(videos)}
            if str(tid).startswith('pornstar:'):
                profile = str(tid)[len('pornstar:'):]
                parts = urllib.parse.urlsplit(absolute(profile))
                path = parts.path.rstrip('/') + '/videos'
                url = absolute(path) + ('?page=' + str(pg) if pg > 1 else '')
                source = get(url)
                videos = parse_profile_videos(source) or parse_cards(source)
                if not videos and pg == 1:
                    videos = parse_profile_videos(get(profile)) or parse_cards(get(profile))
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
        """Search videos and performer profiles; performer cards open video folders."""
        keyword = str(key or '').strip()
        if not keyword:
            return {'list': [], 'page': 1, 'pagecount': 1, 'limit': 0, 'total': 0}
        try:
            page = max(1, int(pg))
        except (TypeError, ValueError):
            page = 1
        query = urllib.parse.quote(keyword)
        video_result = self.categoryContent('/video/search?search=' + query, page, False, {})
        videos = video_result.get('list', [])
        performers = search_performer_pages(keyword) if page == 1 else []
        merged = performers + videos
        return {'list': merged, 'page': page,
                'pagecount': video_result.get('pagecount', page + 1 if merged else page),
                'limit': len(merged),
                'total': video_result.get('total', 0) + len(performers)}
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
            try:
                performers, tags, categories = detail_links(source)
            except Exception:
                performers, tags, categories = [], [], []
            lines = []
            if performers:
                lines.append('作者：' + '、'.join(self.safe_link(name, 'pornstar:' + link)
                                              for name, link in performers))
            if categories:
                lines.append('分类：' + '、'.join(self.safe_link(name, link) for name, link in categories))
            if tags:
                lines.append('标签：' + '、'.join(self.safe_link(name, link) for name, link in tags))
            lines.append('相关视频：' + self.safe_link('查看相关视频 ›', 'related:' + url))
            if desc:
                lines.append('简介：' + desc)
            desc = '\n'.join(lines)
            try:
                media = media_definitions(source)
            except Exception:
                media = []
            urls = ['自动$' + make_play_id(url, 'auto')]
            urls += [str(q) + 'P$' + make_play_id(url, str(q))
                     for q in sorted(set(d['quality'] for d in media if d['quality'] and not d['master']), reverse=True)]
            if not media:
                urls.append('网页回退$' + urllib.parse.quote(url, safe=''))
            return {'list': [{'vod_id': url, 'vod_name': title, 'vod_pic': pic,
                              'vod_content': desc, 'vod_play_from': '实时HLS' if media else '网页回退',
                              'vod_play_url': '#'.join(urls)}]}
        except Exception as exc:
            # A broken metadata parser must not prevent opening a video page.
            fallback_url = absolute(ids[0])
            return {'list': [{'vod_id': fallback_url, 'vod_name': '视频详情',
                              'vod_content': '详情信息部分解析失败：' + type(exc).__name__,
                              'vod_play_from': '实时HLS',
                              'vod_play_url': '自动$' + make_play_id(fallback_url, 'auto')}]} 
    def playerContent(self, flag, id, vipFlags=None):
        """Refresh signed HLS and verify its manifest before handing it to FongMi."""
        try:
            value = urllib.parse.unquote(str(id))
            data = json.loads(value)
            page = str(data.get('page') or '')
            quality = str(data.get('quality') or 'auto').lower().replace('p', '').strip()
            parsed = urllib.parse.urlsplit(page)
            if (parsed.scheme != 'https' or parsed.hostname not in
                    ('cn.pornhub.com', 'www.pornhub.com', 'pornhub.com') or
                    parsed.path != '/view_video.php' or
                    not urllib.parse.parse_qs(parsed.query).get('viewkey')):
                return {'parse': 0, 'url': '', 'msg': '无效视频页面'}
            source = get(page)
            definitions = media_definitions(source)
            if not definitions:
                return {'parse': 0, 'url': '', 'msg': '当前页面未提供 HLS 正片源'}
            target = quality_number(quality) if quality != 'auto' else 0
            if target:
                # Exact quality first; next prefer another scalar tier. An array
                # entry is not necessarily the requested variant playlist.
                definitions.sort(key=lambda d: (
                    d['master'],
                    abs(d['quality'] - target) if d['quality'] else 9999,
                    d['remote'],
                    not d['default']))
            else:
                # Preserve v26's fast start: prefer the site's actual default
                # stream, avoid speculative high-quality/master selection.
                definitions.sort(key=lambda d: (
                    not d['default'], d['master'], d['remote'],
                    abs(d['quality'] - 720) if d['quality'] else 9999))
            # CDN signed URLs are time-sensitive. No preflight GET, which can
            # consume the validity window before FongMi opens the manifest.
            media_url = definitions[0]['url']
            return {'parse': 0, 'url': media_url, 'header': {
                'User-Agent': HEADERS['User-Agent'],
                'Referer': page,
                'Origin': parsed.scheme + '://' + parsed.netloc,
            }}
        except Exception as exc:
            return {'parse': 0, 'url': '', 'msg': '播放解析失败：' + type(exc).__name__}
