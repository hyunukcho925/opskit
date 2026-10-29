"""Telegram Bot API sendMessage over urllib. Stdlib only, never raises."""
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.telegram.org/bot{}/sendMessage"
LIMIT = 4000  # Telegram hard limit is 4096; leave room
SEEN = os.path.join(os.environ.get("LOCALAPPDATA", "."), "opskit", "telegram-seen.json")


def split_text(text, limit=LIMIT):
    """Split into chunks <= limit, on line boundaries; a single overlong line is hard-cut."""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for line in text.splitlines(keepends=True):
        if len(cur) + len(line) > limit and cur:
            chunks.append(cur)
            cur = ""
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        cur += line
    if cur:
        chunks.append(cur)
    return [c.rstrip("\n") for c in chunks if c.strip()]


def brief(text, lines=8, width=120, log=None) -> str:
    """Owner rule: Telegram says only what went wrong; details stay in logs.

    Keeps the first line, then at most `lines` non-blank lines, each trimmed to `width`. When lines
    are dropped, appends `… 외 K건` (plus ` (로그: <log>)` when log is given).
    """
    head, *rest = (text or "").splitlines() or [""]
    rest = [r for r in rest if r.strip()]
    out = [s if len(s) <= width else s[:width - 1] + "…" for s in [head] + rest[:lines]]
    if len(rest) > lines:
        out.append(f"… 외 {len(rest) - lines}건" + (f" (로그: {log})" if log else ""))
    return "\n".join(out)


def repeat_tag(text, today=None, seen_file=None):
    """An alert (first line starts with ⚠ or 🚨) sent again on consecutive days gets "🔁 N일째 같은 알림" on top.

    Same alert = same first line with digits ignored (dates, counts and ids change daily). A daily repeat of one
    failure reads as noise after day two (tistory 2026-10-27~29), so the streak is spelled out. Never raises.
    """
    head = (text or "").lstrip().split("\n", 1)[0]
    if not head.startswith(("⚠", "🚨")):
        return text
    try:
        f = seen_file or SEEN
        today = today or datetime.date.today()
        try:
            with open(f, encoding="utf-8") as fh:
                seen = json.load(fh)
        except (OSError, ValueError):
            seen = {}
        key = re.sub(r"\d+", "#", head)[:200]
        days = set(seen.get(key, [])) | {today.isoformat()}
        n, d = 0, today
        while d.isoformat() in days:
            n, d = n + 1, d - datetime.timedelta(days=1)
        seen[key] = sorted(days)[-14:]
        cutoff = (today - datetime.timedelta(days=14)).isoformat()
        seen = {k: v for k, v in seen.items() if v and v[-1] >= cutoff}
        os.makedirs(os.path.dirname(f) or ".", exist_ok=True)
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(seen, fh, ensure_ascii=False, indent=1)
        return f"🔁 {n}일째 같은 알림\n{text}" if n >= 2 else text
    except Exception as e:
        print(f"[opskit.telegram] repeat_tag skipped: {type(e).__name__}", file=sys.stderr)
        return text


def _post(token, payload, timeout):
    """-> (http_status, description). status 0 = request never got an HTTP answer."""
    data = urllib.parse.urlencode(payload).encode()
    try:
        with urllib.request.urlopen(API.format(token), data, timeout=timeout) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:  # str(e) is safe, but never echo e.url (has the token)
        try:
            desc = json.load(e).get("description", "")
        except Exception:
            desc = ""
        return e.code, desc
    except Exception as e:  # URLError, timeout, ...
        return 0, f"{type(e).__name__}: {getattr(e, 'reason', e)}".replace(token, "***")


def send(text, *, chat_id=None, token=None, parse_mode=None, timeout=20, silent=False,
         disable_preview=False) -> bool:
    """Send text (split if > LIMIT). True only if every part was delivered.

    A 400 with parse_mode set (usually an entity parse error) is retried once as plain text:
    delivery beats formatting. Failures print one line to stderr and return False.
    """
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("[opskit.telegram] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set - skipped", file=sys.stderr)
        return False
    for part in split_text(repeat_tag(text)):
        payload = {"chat_id": chat_id, "text": part}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if silent:
            payload["disable_notification"] = "true"
        if disable_preview:
            payload["disable_web_page_preview"] = "true"
        status, desc = _post(token, payload, timeout)
        if status == 400 and parse_mode:
            payload.pop("parse_mode")
            status, desc = _post(token, payload, timeout)
        if status != 200:
            print(f"[opskit.telegram] send failed (chat {chat_id}): HTTP {status} {desc}"[:300], file=sys.stderr)
            return False
    return True
