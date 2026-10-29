"""Smoke check of the Cloudflare Workers price sites: home + a few random sitemap URLs must not answer 5xx.

python -m opskit.sitecheck watch          hourly task: alert when a site starts failing and when it recovers
python -m opskit.sitecheck deploy         run in a site repo after `opennextjs-cloudflare deploy` (package.json
                                          "deploy"): on failure roll the worker back to the previous version
Homes are often served from cache, so they stay 200 while every dynamic page 500s (houseprice 2026-10-26~29).
"""
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from opskit import env, telegram

SITES = {  # worker name -> base URL
    'houseprice-web': 'https://www.houseprice.co.kr',
    'couprice-web': 'https://www.couprice.co.kr',
    'olyoungprice-web': 'https://www.olyoungprice.co.kr',
    'nstoreprice-web': 'https://www.nstoreprice.co.kr',
    'pricetory-web': 'https://www.pricetory.co.kr',
}
ENV_FILES = (Path(r'C:\dev\dashboard\dashboard-web\.env.local'), Path(r'C:\dev\dashboard\dashboard-web\.env'))  # Telegram, as ops-digest
STATE = Path(os.environ.get('LOCALAPPDATA', '.')) / 'opskit' / 'sitecheck.json'
UA = 'Mozilla/5.0 opskit-sitecheck'


def get(url, timeout=30):
    """-> (status, body). status 0 = no HTTP answer."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=timeout) as r:
            return r.status, r.read().decode('utf-8', 'ignore')
    except urllib.error.HTTPError as e:
        return e.code, ''
    except Exception:
        return 0, ''


def sample(base, n=3):
    """Home + n random page URLs from the sitemap (one random child sitemap when it is an index)."""
    _, xml = get(base + '/sitemap.xml')
    if '<sitemap>' in xml:
        _, xml = get(random.choice(re.findall(r'<loc>\s*([^<\s]+)', xml)))
    locs = [u for u in re.findall(r'<loc>\s*([^<\s]+)', xml) if u.rstrip('/') != base]
    return [base + '/'] + random.sample(locs, min(n, len(locs)))


def check(base):
    """Problems ('<status> <url>') for one site; an empty sitemap is a problem too."""
    urls = sample(base)
    problems = [] if len(urls) > 1 else [f'no URLs in {base}/sitemap.xml']
    for u in urls:
        status, _ = get(u)
        if status == 0 or status >= 500:
            problems.append(f'{status or "no answer"} {u}')
    return problems


def check_retry(base, tries=3, wait=20):
    """A site fails only when every try finds a problem (a fresh deploy or one slow render is not an outage)."""
    for i in range(tries):
        problems = check(base)
        if not problems:
            return []
        if i < tries - 1:
            time.sleep(wait)
    return problems


def alert(text):
    env.load(*ENV_FILES)
    telegram.send(text)


def watch():
    state = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
    for worker, base in SITES.items():
        problems = check_retry(base)
        was = state.get(worker)
        if problems and not was:
            alert(telegram.brief(f'🚨 {base} 5xx: 사이트 점검 실패\n' + '\n'.join(problems)))
        elif not problems and was:
            alert(f'✅ {base} 복구됨 (실패 시작 {was})')
        state[worker] = (was or time.strftime('%Y-%m-%d %H:%M')) if problems else None
        print(worker, 'FAIL ' + '; '.join(problems) if problems else 'ok', flush=True)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')


def wrangler(*args):
    return subprocess.run('npx wrangler ' + ' '.join(args), shell=True, capture_output=True, text=True, encoding='utf-8')


def deploy():
    """In a site repo right after deploy: check, and on failure roll back to the previous deployment's version."""
    worker = re.search(r'"name"\s*:\s*"([^"]+)"', Path('wrangler.jsonc').read_text(encoding='utf-8'))[1]
    base = SITES[worker]
    time.sleep(10)  # let the new version reach the edge
    problems = check_retry(base)
    if not problems:
        print(f'sitecheck {base}: ok', flush=True)
        return 0
    deps = json.loads(wrangler('deployments', 'list', '--json').stdout)  # oldest first
    prev = deps[-2]['versions'][0]['version_id'] if len(deps) > 1 else None
    rb = wrangler('rollback', prev, '--message', '"sitecheck: deploy answered 5xx"', '-y') if prev else None
    after = check_retry(base) if rb and rb.returncode == 0 else problems
    how = (f'이전 버전 {prev[:8]} 으로 롤백, ' + ('복구됨' if not after else '롤백 뒤에도 실패') if rb and rb.returncode == 0
           else '롤백 실패: ' + ((rb.stderr or rb.stdout)[-200:] if rb else '이전 버전 없음'))
    alert(telegram.brief(f'🚨 {worker} 배포 후 5xx, {how}\n' + '\n'.join(problems)))
    print(f'sitecheck {base}: FAILED, {how}\n' + '\n'.join(problems), file=sys.stderr, flush=True)
    return 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'watch':
        watch()
    elif mode == 'deploy':
        sys.exit(deploy())
    else:
        sys.exit(__doc__)
