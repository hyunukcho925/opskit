"""Telegram Bot API sendMessage over urllib. Stdlib only, never raises."""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.telegram.org/bot{}/sendMessage"
LIMIT = 4000  # Telegram hard limit is 4096; leave room


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
    for part in split_text(text):
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
