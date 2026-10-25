# opskit

Shared helpers for the local Task Scheduler jobs under `C:\dev`.

**Rule: standard library only.** No third-party dependencies, ever — every job's interpreter must be able to import it.

| Module | What it does |
|---|---|
| `opskit.env` | `read(path)` parses a KEY=VALUE `.env` (comments, `export `, surrounding quotes). `load(*paths, override=False)` also copies keys into `os.environ` (existing keys win unless `override`). `get(key, default, paths)`. |
| `opskit.telegram` | `send(text, *, chat_id, token, parse_mode, timeout, silent, disable_preview) -> bool`. Defaults from `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`. Splits >4000 chars on line boundaries, retries a parse_mode 400 once as plain text, never raises. `brief(text, lines=8, width=120, log=None)` caps a message: first line + at most `lines` lines trimmed to `width`, then `… 외 K건 (로그: <log>)` (owner rule: Telegram says only what went wrong). |
| `opskit.jev` | Shared copy of the Jev (TypeSafe System One) evaluator, incl. image `assets=`. |

## Install

```
C:\Users\chohy\AppData\Local\Programs\Python\Python311\python.exe -m pip install -e C:\dev\opskit
<repo>\.venv\Scripts\python.exe -m pip install -e C:\dev\opskit
```

## Test

```
python tests/test_opskit.py
```
