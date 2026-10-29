"""Self-check: python tests/test_opskit.py (also runs under pytest)."""
import io
import json
import os
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opskit import env, telegram  # noqa: E402


def test_env_parsing():
    with tempfile.TemporaryDirectory() as d:
        a, b = Path(d) / "a.env", Path(d) / "b.env"
        a.write_text('# comment\n\nexport OPSKIT_A="quoted value"\nOPSKIT_B=\'single\'\n'
                     'OPSKIT_C=plain=with=eq\nOPSKIT_D="unmatched\'\nnot a pair\n', encoding="utf-8")
        b.write_text("OPSKIT_A=from_b\nOPSKIT_E=only_b\n", encoding="utf-8")
        assert env.read(a) == {"OPSKIT_A": "quoted value", "OPSKIT_B": "single",
                               "OPSKIT_C": "plain=with=eq", "OPSKIT_D": "\"unmatched'"}
        os.environ["OPSKIT_B"] = "preset"
        try:
            merged = env.load(a, b, Path(d) / "missing.env")
            assert merged["OPSKIT_A"] == "quoted value"  # earlier file wins
            assert os.environ["OPSKIT_B"] == "preset"     # existing env wins
            assert os.environ["OPSKIT_E"] == "only_b"
            env.load(b, override=True)
            assert os.environ["OPSKIT_A"] == "from_b"
            assert env.get("OPSKIT_NOPE", "dflt") == "dflt"
        finally:
            for k in list(os.environ):
                if k.startswith("OPSKIT_"):
                    del os.environ[k]


def test_split_text():
    assert telegram.split_text("short") == ["short"]
    lines = [f"line {i:04d} " + "x" * 90 for i in range(100)]  # 100 lines * ~100 chars
    parts = telegram.split_text("\n".join(lines), limit=1000)
    assert all(len(p) <= 1000 for p in parts) and len(parts) > 1
    assert "\n".join(parts).split("\n") == lines  # nothing lost, cut only at line ends
    long = telegram.split_text("a" * 2500, limit=1000)
    assert [len(p) for p in long] == [1000, 1000, 500]


def test_brief():
    assert telegram.brief("one") == "one"
    assert telegram.brief("t\n\na\nb", lines=2) == "t\na\nb"  # blank lines dropped, nothing cut
    assert telegram.brief("x" * 10, width=5) == "xxxx…"
    out = telegram.brief("t\n" + "\n".join(f"l{i}" for i in range(9)), lines=3, log="logs/a.log")
    assert out == "t\nl0\nl1\nl2\n… 외 6건 (로그: logs/a.log)", out
    assert telegram.brief("t\na\nb\nc", lines=1).endswith("… 외 2건")


class _Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code, desc):
    return urllib.error.HTTPError("https://api.telegram.org/botSECRET/sendMessage", code, "err", {},
                                  io.BytesIO(json.dumps({"ok": False, "description": desc}).encode()))


def test_400_retries_plain_text():
    sent = []

    def fake_urlopen(url, data, timeout):
        sent.append(data.decode())
        if "parse_mode" in data.decode():
            raise _http_error(400, "Bad Request: can't parse entities")
        return _Resp()

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        assert telegram.send("<b>x", token="T", chat_id="1", parse_mode="HTML") is True
    assert len(sent) == 2 and "parse_mode" in sent[0] and "parse_mode" not in sent[1]


def test_failure_returns_false_without_token_in_message():
    err = io.StringIO()
    with mock.patch("urllib.request.urlopen", side_effect=_http_error(403, "Forbidden")), \
            mock.patch("sys.stderr", err):
        assert telegram.send("hi", token="SECRET", chat_id="1") is False
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down SECRET")), \
            mock.patch("sys.stderr", err):
        assert telegram.send("hi", token="SECRET", chat_id="1") is False
    out = err.getvalue()
    assert "403" in out and "SECRET" not in out


def test_repeat_tag():
    import datetime
    with tempfile.TemporaryDirectory() as d:
        f, day = str(Path(d) / "seen.json"), datetime.date(2026, 10, 27)
        msg = lambda n: f"🚨 tistory 실패: exit 1 for 2026-10-{n}-farfetch-sale\nlog {n}"
        assert telegram.repeat_tag(msg(13), day, f) == msg(13)
        assert telegram.repeat_tag(msg(13), day, f) == msg(13)  # twice the same day is still day 1
        assert telegram.repeat_tag(msg(14), day + datetime.timedelta(1), f).startswith("🔁 2일째 같은 알림\n🚨")
        assert telegram.repeat_tag(msg(15), day + datetime.timedelta(2), f).startswith("🔁 3일째")
        assert telegram.repeat_tag(msg(16), day + datetime.timedelta(4), f) == msg(16)  # gap resets the streak
        assert telegram.repeat_tag("일일 리포트 2026-10-28", day, f) == "일일 리포트 2026-10-28"  # not an alert


def test_sitecheck():
    from opskit import sitecheck
    index = "<sitemapindex><sitemap><loc>https://s.kr/sm/0.xml</loc></sitemap></sitemapindex>"
    urls = "".join(f"<url><loc>https://s.kr/goods/{i}</loc></url>" for i in range(5)) + "<url><loc>https://s.kr</loc></url>"
    pages = {"https://s.kr/sitemap.xml": (200, index), "https://s.kr/sm/0.xml": (200, urls), "https://s.kr/": (200, "")}
    fake = lambda bad: lambda u, timeout=30: pages.get(u, (500 if bad else 200, ""))
    with mock.patch.object(sitecheck, "get", fake(False)):
        assert sitecheck.check("https://s.kr") == []
    with mock.patch.object(sitecheck, "get", fake(True)):  # cached home 200, every product 500
        assert len(sitecheck.check("https://s.kr")) == 3
    with tempfile.TemporaryDirectory() as d, mock.patch.object(sitecheck, "SITES", {"w": "https://s.kr"}), \
            mock.patch.object(sitecheck, "STATE", Path(d) / "s.json"), mock.patch.object(sitecheck, "alert") as al:
        for bad, sent in ((True, "🚨"), (True, None), (False, "✅"), (False, None)):
            al.reset_mock()
            with mock.patch.object(sitecheck, "check_retry", lambda b: ["500 x"] if bad else []):
                sitecheck.watch()
            assert (al.call_args[0][0][:1] if al.called else None) == sent


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
