
# coding: utf-8
"""PMVHaven / FongMi Python Spider. Based on supplied homepage and video HTML."""
import re, json, html, urllib.parse, urllib.request, urllib.error, time
from html.parser import HTMLParser
try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider(object): pass

HOST='https://pmvhaven.com'
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
HEADERS={'User-Agent':UA,'Referer':HOST+'/','Accept-Language':'en-US,en;q=0.9'}
THUMB='https://pmvhavencloud.s3.eu-west-par.io.cloud.ovh.net/thumbnails/{}/thumb_lg.webp'

def absolute(u): return urllib.parse.urljoin(HOST,html.unescape(u or ''))
def request(url, timeout=12, headers=None, max_bytes=2000000):
    req=urllib.request.Request(url,headers=dict(HEADERS,**(headers or {})))
    with urllib.request.urlopen(req,timeout=timeout) as r: return r.read(max_bytes)
def fetch(url,timeout=12): return request(absolute(url),timeout=timeout).decode('utf-8','replace')
def clean(s): return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s or ''))).strip()
def canonical(url):
    p=urllib.parse.urlsplit(absolute(url))
    return urllib.parse.urlunsplit((p.scheme,p.netloc,p.path,'',''))

class Cards(HTMLParser):
    def __init__(self): super().__init__();self.cards=[];self.cur=None;self.depth=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='a' and '/video/' in a.get('href','') and self.cur is None:
            self.cur={'href':a['href'],'pic':'','title':'','text':''};self.depth=1;return
        if self.cur is None:return
        if tag=='a':self.depth+=1
        if tag=='img':
            choices=[a.get(x,'') for x in ('src','data-src','data-original')]
            for src in choices:
                if '/thumbnails/' in src:
                    self.cur['pic']=src;self.cur['title']=a.get('alt','');break
    def handle_data(self,data):
        if self.cur:self.cur['text']+=data+' '
    def handle_endtag(self,tag):
        if tag=='a' and self.cur:
            self.depth-=1
            if self.depth<=0:self.cards.append(self.cur);self.cur=None

def cards(page):
    p=Cards();p.feed(page);out=[];seen=set()
    for c in p.cards:
        url=canonical(c['href']);vid=url.split('/')[-1]
        if vid in seen:continue
        seen.add(vid)
        key=vid.rsplit('_',1)[-1]
        pic=absolute(c['pic']) if '/thumbnails/' in c['pic'] else (THUMB.format(key) if re.fullmatch(r'[a-f0-9]{24}',key) else '')
        out.append({'vod_id':url,'vod_name':c['title'] or clean(c['text']) or vid.replace('-',' '),'vod_pic':pic,'vod_remarks':''})
    return out

def nuxt(page):
    m=re.search(r'<script[^>]+id=["\']__NUXT_DATA__["\'][^>]*>(.*?)</script>',page,re.S|re.I)
    if not m:return []
    try: obj=json.loads(m.group(1))
    except Exception:return []
    return [x for x in obj if isinstance(x,str)] if isinstance(obj,list) else []

def streams(page):
    found=[]
    for x in nuxt(page):
        if x.startswith('http') and re.search(r'\.m3u8(?:\?|$)|\.mp4(?:\?|$)',x,re.I) and 'preview' not in x.lower():found.append(html.unescape(x))
    def rank(u):
        m=re.search(r'(\d{3,4})p\.m3u8',u,re.I)
        return (0,-int(m.group(1))) if m else ((1,0) if 'master.m3u8' in u else (2,0))
    return sorted(set(found),key=rank)

def metadata(page):
    t=re.search(r'<title[^>]*>(.*?)</title>',page,re.S|re.I)
    title=clean(t.group(1)).replace(' - PMVHaven','') if t else ''
    creator='';creator_url=''
    for u,label in re.findall(r'<a[^>]+href=["\'](/users/[^"\']+)["\'][^>]*>(.*?)</a>',page,re.S|re.I):
        label=clean(label).replace(' Creator','').strip()
        if label:creator=label;creator_url=absolute(u);break
    tags=[];seen=set()
    for u,label in re.findall(r'<a[^>]+href=["\'](/search\?tags=[^"\']+)["\'][^>]*>(.*?)</a>',page,re.S|re.I):
        label=clean(label).lstrip('#').strip();u=absolute(u)
        if label and u not in seen:tags.append((label,u));seen.add(u)
    pic=''
    for m in re.finditer(r'<meta\s+[^>]*>',page,re.I):
        tag=m.group(0)
        if 'og:image' in tag:
            x=re.search(r'content=["\']([^"\']+)',tag,re.I)
            if x and '/thumbnails/' in x.group(1):pic=html.unescape(x.group(1));break
    return title,creator,creator_url,tags,pic

def check(url):
    """Quick probe; only one quality at a time to avoid excessive startup latency."""
    try:
        if '.m3u8' not in url.lower():return bool(request(url,timeout=3,headers={'Range':'bytes=0-127'},max_bytes=64))
        body=request(url,timeout=3,max_bytes=120000).decode('utf-8','replace')
        if '#EXTM3U' not in body:return False
        if '#EXT-X-STREAM-INF' in body:
            child=next((line.strip() for line in body.splitlines() if line.strip() and not line.startswith('#')),None)
            if not child:return False
            url=urllib.parse.urljoin(url,child)
            body=request(url,timeout=3,max_bytes=120000).decode('utf-8','replace')
        if '#EXTM3U' not in body:return False
        match=re.search(r'#EXT-X-MAP:[^\n]*URI=["\']([^"\']+)',body)
        segment=match.group(1) if match else next((line.strip() for line in body.splitlines() if line.strip() and not line.startswith('#')),None)
        if not segment:return False
        return bool(request(urllib.parse.urljoin(url,segment),timeout=3,headers={'Range':'bytes=0-127'},max_bytes=64))
    except Exception:return False

def pack_episodes(items,limit=35):
    seen=set();out=[]
    for v in items[:limit]:
        url=v.get('vod_id','')
        if not url or url in seen:continue
        seen.add(url)
        name=(v.get('vod_name') or '视频').replace('$',' ').replace('#',' ').replace('$$$',' ')
        out.append(name+'$'+url)
    return '#'.join(out)

class Spider(BaseSpider):
    def getName(self):return 'PMVHaven'
    def init(self,extend=''):pass
    def destroy(self):pass
    def isVideoFormat(self,url):return bool(re.search(r'\.m3u8(?:\?|$)|\.mp4(?:\?|$)',url,re.I))
    def manualVideoCheck(self):return False
    def homeContent(self,filter):
        return {'class':[{'type_id':'/browse','type_name':'所有视频'}, {'type_id':'/trending','type_name':'热门视频'}, {'type_id':'/popular','type_name':'最受欢迎'}]}
    def homeVideoContent(self):
        try:return {'list':cards(fetch(HOST+'/'))}
        except Exception:return {'list':[]}
    def categoryContent(self,tid,pg,filter,extend):
        try:pg=max(1,int(pg or 1))
        except Exception:pg=1
        path=tid if str(tid).startswith(('/','http')) else '/browse'
        url=absolute(path)
        if pg>1:url+=('&' if '?' in url else '?')+'page='+str(pg)
        try:lst=cards(fetch(url))
        except Exception:lst=[]
        return {'list':lst,'page':pg,'pagecount':pg+1 if lst else pg,'limit':30,'total':999999 if lst else 0}
    def searchContent(self,key,quick,pg='1'):
        try:pg=max(1,int(pg or 1))
        except Exception:pg=1
        key=str(key)
        if key.startswith('标签:'):params={'tags':key[3:],'page':pg}
        else:params={'q':key[3:] if key.startswith('作者:') else key,'page':pg}
        try:lst=cards(fetch(HOST+'/search?'+urllib.parse.urlencode(params)))
        except Exception:lst=[]
        return {'list':lst,'page':pg,'pagecount':pg+1 if lst else pg,'limit':30,'total':999999 if lst else 0}
    def detailContent(self,ids):
        url=canonical(ids[0])
        try:page=fetch(url)
        except Exception:return {'list':[]}
        title,creator,creator_url,tags,pic=metadata(page)
        vid=url.rsplit('_',1)[-1]
        if not pic and re.fullmatch(r'[a-f0-9]{24}',vid):pic=THUMB.format(vid)
        # FongMi native detail text is not clickable. Put creator/tag videos in
        # actual selectable play-source tabs; tapping an episode navigates playback.
        related=cards(page)
        main=[{'vod_id':url,'vod_name':title or '当前视频'}]+[v for v in related if v['vod_id']!=url]
        source_names=['连续播放'];source_urls=[pack_episodes(main)]
        if creator_url:
            try:creator_items=cards(fetch(creator_url,timeout=5))
            except Exception:creator_items=[]
            if creator_items:
                source_names.append('创作者·'+creator[:20]);source_urls.append(pack_episodes(creator_items))
        for label,tagurl in tags[:4]:
            try:tagitems=cards(fetch(tagurl,timeout=5))
            except Exception:tagitems=[]
            if tagitems:
                source_names.append('标签·'+label[:20]);source_urls.append(pack_episodes(tagitems))
        vod={'vod_id':url,'vod_name':title or url.split('/')[-1], 'vod_pic':pic,
             'vod_actor':creator,'vod_director':creator,
             'vod_content':'创作者：'+(creator or '未知')+'\n标签：'+', '.join(x[0] for x in tags)+'\n在下方播放源切换「创作者」或「标签」，选择相应作品。',
             'vod_play_from':'$$$'.join(source_names),'vod_play_url':'$$$'.join(source_urls)}
        return {'list':[vod]}
    def playerContent(self,flag,id,vipFlags):
        url=canonical(id)
        try:choices=streams(fetch(url))
        except Exception:choices=[]
        if not choices:return {'parse':1,'url':url}
        # 1080p first, fallback to 720p/480p etc. Probe at most 3 candidates.
        for stream in choices[:3]:
            if check(stream):return {'parse':0,'url':stream,'header':{'User-Agent':UA,'Referer':HOST+'/','Origin':HOST}}
        # If probes are blocked but playlists exist, allow player to attempt.
        return {'parse':0,'url':choices[0],'header':{'User-Agent':UA,'Referer':HOST+'/','Origin':HOST}}
    def localProxy(self,param):return None
