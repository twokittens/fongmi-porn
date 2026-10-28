# coding: utf-8
"""PMVHaven FongMi Python Spider; based on supplied homepage and video-page HTML."""
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

HOST = 'https://pmvhaven.com'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
HEADERS = {'User-Agent': UA, 'Referer': HOST + '/', 'Accept-Language': 'en-US,en;q=0.9'}

class _Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.items=[]; self.current=None
    def handle_starttag(self, tag, attrs):
        d=dict(attrs)
        if tag=='a' and d.get('href','').startswith('/video/'):
            self.current={'href':d['href'],'title':'','pic':'','text':''}
        if tag=='img' and self.current:
            self.current['pic']=d.get('src') or d.get('data-src') or ''
            self.current['title']=d.get('alt') or self.current['title']
    def handle_data(self, data):
        if self.current: self.current['text']+=data.strip()+' '
    def handle_endtag(self, tag):
        if tag=='a' and self.current:
            self.items.append(self.current); self.current=None

def fetch(url):
    req=urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=16) as r:
        return r.read().decode('utf-8','replace')

def full(url):
    return urllib.parse.urljoin(HOST, html.unescape(url or ''))

def parse_cards(page):
    parser=_Links(); parser.feed(page)
    result=[]; seen=set()
    for item in parser.items:
        link=full(item['href'].split('?')[0]); vid=link.rsplit('/',1)[-1]
        if vid in seen: continue
        seen.add(vid)
        title=item['title'] or item['text'].strip() or vid.replace('-',' ')
        result.append({'vod_id':link,'vod_name':title,'vod_pic':full(item['pic']) if item['pic'] else '', 'vod_remarks':''})
    return result

def nuxt_strings(page):
    match=re.search(r'<script[^>]*id=["\']__NUXT_DATA__["\'][^>]*>(.*?)</script>',page,re.S|re.I)
    if not match: return []
    try: data=json.loads(match.group(1))
    except Exception: return []
    return [v for v in data if isinstance(v,str)] if isinstance(data,list) else []

def streams(page):
    values=nuxt_strings(page)
    found=[]
    for v in values:
        if v.startswith('http') and ('.m3u8' in v or re.search(r'\.mp4(?:\?|$)',v)):
            if 'preview' in v.lower(): continue
            found.append(v)
    # Prioritize master playlist, then highest-resolution variants.
    def rank(u):
        m=re.search(r'(\d{3,4})p\.m3u8',u)
        return (3 if 'master.m3u8' in u else 2 if m else 1 if '.m3u8' in u else 0, int(m.group(1)) if m else 0)
    return sorted(set(found),key=rank,reverse=True)

def details(page):
    title=re.search(r'<title[^>]*>(.*?)</title>',page,re.S|re.I)
    title=html.unescape(re.sub('<[^>]+>','',title.group(1))).replace(' - PMVHaven','').strip() if title else ''
    creator=re.search(r'<a[^>]+href=["\'](/users/[^"\']+)["\'][^>]*>(.*?)</a>',page,re.S|re.I)
    creator_name=html.unescape(re.sub('<[^>]+>',' ',creator.group(2))).strip() if creator else ''
    if not creator_name:
        for m in re.finditer(r'<a[^>]+href=["\'](/users/[^"\']+)["\'][^>]*>(.*?)</a>',page,re.S|re.I):
            name=html.unescape(re.sub('<[^>]+>',' ',m.group(2))).strip()
            if name: creator_name=name.replace(' Creator','').strip(); break
    creator_url=full(creator.group(1)) if creator else ''
    tags=[]
    for href,label in re.findall(r'<a[^>]+href=["\'](/search\?tags=[^"\']+)["\'][^>]*>(.*?)</a>',page,re.S|re.I):
        label=html.unescape(re.sub('<[^>]+>',' ',label)).strip().lstrip('#')
        if label and (label,full(href)) not in tags: tags.append((label,full(href)))
    pic=''
    meta=re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',page,re.I)
    if meta: pic=html.unescape(meta.group(1))
    if not pic:
        match=re.search(r'https?[^"\s<>]+/thumbnails/[^"\s<>]+',page)
        if match: pic=html.unescape(match.group(0))
    return title,creator_name,creator_url,tags,pic

class Spider(BaseSpider):
    def getName(self): return 'PMVHaven'
    def init(self, extend=''): pass
    def isVideoFormat(self,url): return bool(re.search(r'\.m3u8(?:\?|$)|\.mp4(?:\?|$)',url,re.I))
    def manualVideoCheck(self): return False
    def destroy(self): pass
    def homeContent(self,filter):
        return {'class':[
            {'type_id':'/browse','type_name':'所有视频'},
            {'type_id':'/trending','type_name':'热门视频'},
            {'type_id':'/popular','type_name':'最受欢迎'}
        ]}
    def homeVideoContent(self):
        try: return {'list':parse_cards(fetch(HOST+'/'))[:30]}
        except Exception: return {'list':[]}
    def categoryContent(self,tid,pg,filter,extend):
        pg=max(1,int(pg or 1))
        path=tid if str(tid).startswith('/') else '/browse'
        # User/Tag pages can be used as category IDs by compatible clients.
        url=full(path)
        if pg>1:
            sep='&' if '?' in url else '?'
            url+=sep+'page='+str(pg)
        try: cards=parse_cards(fetch(url))
        except Exception: cards=[]
        return {'list':cards,'page':pg,'pagecount':pg+1 if cards else pg,'limit':30,'total':999999 if cards else 0}
    def searchContent(self,key,quick,pg='1'):
        pg=max(1,int(pg or 1))
        url=HOST+'/search?'+urllib.parse.urlencode({'q':key,'page':pg})
        try: cards=parse_cards(fetch(url))
        except Exception: cards=[]
        return {'list':cards,'page':pg,'pagecount':pg+1 if cards else pg,'limit':30,'total':999999 if cards else 0}
    def detailContent(self,ids):
        url=ids[0]
        try: page=fetch(url)
        except Exception: return {'list':[]}
        title,creator,creator_url,tags,pic=details(page)
        sources=streams(page)
        # Use page URL as play ID to fetch a fresh stream when tapped.
        vod={'vod_id':url,'vod_name':title or url.rsplit('/',1)[-1], 'vod_pic':pic,
             'vod_actor':creator, 'vod_director':creator,
             'vod_content':'创作者：'+(creator or '未知')+'\n创作者主页：'+creator_url+'\n标签：'+', '.join(t[0] for t in tags)+'\n标签地址：'+', '.join(t[1] for t in tags),
             'vod_play_from':'PMVHaven','vod_play_url':'在线播放$'+url}
        # Source discovery is informational; playerContent refreshes the page.
        if not sources: vod['vod_content']+='\n注意：当前 HTML 未发现可直接播放的视频源。'
        return {'list':[vod]}
    def playerContent(self,flag,id,vipFlags):
        try:
            page=fetch(id)
            choices=streams(page)
            if not choices: return {'parse':1,'url':id}
            return {'parse':0,'url':choices[0], 'header':{'User-Agent':UA,'Referer':HOST+'/', 'Origin':HOST}}
        except Exception:
            return {'parse':1,'url':id}
    def localProxy(self,param): return None
