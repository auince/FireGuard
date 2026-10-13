"""Bounded official-source crawler with immutable raw versions and an audit trail."""
import json
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin, urldefrag
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup
from .config import ROOT, directory, read_json, write_json
from .ingest import convert, sha256

AGENT = 'XFAgentResearch/0.1'

def official(url):
    p = urlparse(url)
    h = (p.hostname or '').lower()
    return p.scheme in ('https', 'http') and (h.endswith('.gov.cn') or h == 'gov.cn') and not p.username

def crawl(limit=80, discover=True):
    seeds = read_json(ROOT / 'configs/legal_sources.json', [])
    queue = deque((x, 0) for x in seeds)
    visited, hashes, robots = set(), set(), {}
    manifest = read_json(ROOT / 'data/legal/manifest.json', [])
    by_url = {x['url']: x for x in manifest}
    logs = []
    session = requests.Session()
    session.headers['User-Agent'] = AGENT
    raw_root = directory('data/legal/raw')
    clean_root = directory('data/legal/markdown')
    attempts = 0
    while queue and attempts < limit:
        source, depth = queue.popleft()
        url = urldefrag(source['url'])[0]
        if url in visited or not official(url):
            continue
        visited.add(url)
        attempts += 1
        try:
            host = urlparse(url).netloc
            if host not in robots:
                rp = RobotFileParser()
                rr = session.get(urljoin(url, '/robots.txt'), timeout=12)
                if rr.status_code == 200:
                    rp.parse(rr.text.splitlines())
                    robots[host] = rp
                elif rr.status_code in (401, 403):
                    robots[host] = False
                else:
                    robots[host] = None
            rp = robots[host]
            if rp is False or (rp and not rp.can_fetch(AGENT, url)):
                raise ValueError('robots.txt prohibits this path')
            time.sleep(0.6)
            # Validate every redirect before making a request to the destination.
            current = url
            for _ in range(6):
                if not official(current):
                    raise ValueError('redirect outside government domain')
                response = session.get(current, timeout=(8, 35), allow_redirects=False)
                if response.is_redirect:
                    current = urljoin(current, response.headers['Location'])
                    continue
                break
            response.raise_for_status()
            raw = response.content
            if len(raw) > 35_000_000:
                raise ValueError('document exceeds 35 MB')
            digest = sha256(raw)
            if raw.startswith(bytes.fromhex('d0cf11e0')):
                raise ValueError('旧版 DOC 二进制附件需 LibreOffice 转换，禁止作为 HTML 入库')
            suffix = '.pdf' if raw.startswith(b'%PDF') else '.html'
            if suffix == '.html':
                response.encoding = response.apparent_encoding or 'utf-8'
                raw = response.text.encode('utf-8')
                digest = sha256(raw)
                soup = BeautifulSoup(raw, 'html.parser')
                if discover and depth < 1:
                    for a in soup.find_all('a', href=True):
                        target = urljoin(current, a['href'])
                        title = a.get_text(' ', strip=True)
                        attachment = urlparse(target).path.lower().endswith('.pdf')
                        if official(target) and (attachment or any(k in title for k in ['消防', '防火', '消火栓', '灭火器'])):
                            queue.append(({'url': target, 'title': title or source.get('title', ''),
                                           'kind': 'standard' if attachment else 'reference',
                                           'status': 'unverified', 'discovered_from': url}, depth+1))
            identifier = sha256(url.encode())[:16]
            path = raw_root / f'{identifier}-{digest[:12]}{suffix}'
            path.write_bytes(raw)
            content = convert(path)
            if len(content) < 150 or ('验证码' in content[:150] and len(content) < 1500):
                raise ValueError('empty, index-only or blocked content')
            if digest in hashes:
                continue
            hashes.add(digest)
            md = clean_root / f'{identifier}.md'
            md.write_text(content)
            item = {**source, 'id': identifier, 'url': url, 'resolved_url': current,
                    'fetched_at': datetime.now(timezone.utc).isoformat(), 'sha256': digest,
                    'raw_path': str(path.relative_to(ROOT)), 'markdown_path': str(md.relative_to(ROOT)),
                    'characters': len(content), 'status': source.get('status', 'unverified')}
            by_url[url] = item
            logs.append({'url': url, 'ok': True, 'characters': len(content)})
            print(json.dumps(logs[-1], ensure_ascii=False), flush=True)
        except Exception as e:
            logs.append({'url': url, 'ok': False, 'error': str(e)[:200]})
            print(json.dumps(logs[-1], ensure_ascii=False), flush=True)
        write_json(ROOT / 'data/legal/manifest.json', list(by_url.values()))
        write_json(ROOT / 'data/legal/crawl_report.json', logs)
    return {'documents': len(by_url), 'attempts': attempts, 'success': sum(x['ok'] for x in logs)}
