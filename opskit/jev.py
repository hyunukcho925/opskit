# Shared copy for C:\dev projects (source: discountspot-blog/src/jev.py). Edit here, not in per-repo copies.
"""Jev (TypeSafe System One model) — stdlib only, never raises.

Jev is a NON-generative evaluation model: `state` + typed questions -> probabilities.
It cannot write text or give reasons. Use it only for cheap yes/no, pick-one, or rubric decisions.

    answers = evaluate(
        {"title": "..."},
        {"accessory": {"type": "boolean", "instructions": "Is `title` a phone case or film?"}},
    )
    if answers is None:          # no key / disabled / timeout / API error
        ...existing behaviour... # callers MUST fall back to what they did before Jev

Answer shapes (identical on both transports):
    boolean -> {"type": "boolean", "probability": 0.97}
    choice  -> {"type": "choice", "choice": "billing", "probabilities": {...}, "confidence": 0.99}
    score   -> {"type": "score", "score": 1.97, "probabilities": {...}, "confidence": 0.99}   # 0-based rung index

Transports, first match wins:
    1. TYPESAFE_API_KEY   -> TypeSafe API, POST https://api.typesafe.ai/v1/systemone (documented public contract).
                             JEV_MODEL pins a version (default "jev-latest", which may change without notice).
    2. AI_GATEWAY_API_KEY -> Vercel AI Gateway (or VERCEL_OIDC_TOKEN for local dev). Mirrors the wire format of
                             @ai-sdk/gateway 'evaluation-model' (protocol 0.0.1), which is NOT a documented HTTP API.
Kill switch: JEV_DISABLED=1. Every failure returns None.

Images (experimental, https://docs.typesafe.ai/images): pass `assets={ref: {"type": "image", "format": "jpg",
"data_base64": ...}}` and put `ref` in the state. Sent only on the TYPESAFE_API_KEY transport — otherwise None.
"""
import json
import os
import urllib.request

_TYPESAFE_URL = "https://api.typesafe.ai/v1/systemone"
_GATEWAY_URL = "https://ai-gateway.vercel.sh/v4/ai/evaluation-model"
_warned = False


def _post(url, headers, body, timeout):
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.load(res)


def _via_typesafe(key, state, questions, timeout, assets=None):
    # TypeSafe calls the yes/no primitive "noul" and returns its probability in a `noul` field.
    wire = {k: ({**q, "type": "noul"} if q.get("type") == "boolean" else q) for k, q in questions.items()}
    request = {"model": os.environ.get("JEV_MODEL") or "jev-latest", "state": state, "questions": wire}
    headers = {"Authorization": f"Bearer {key}"}
    if assets:
        request["assets"] = assets
        headers["TypeSafe-Danger-Zone-Images"] = "true"
    body = _post(_TYPESAFE_URL, headers, request, timeout)
    answers = body["answers"]
    for answer in answers.values():
        if answer.get("type") == "noul":
            answer["type"] = "boolean"
            answer["probability"] = answer.pop("noul")
        else:
            answer["confidence"] = float(answer.get("confidence") or 0.0)
    return answers


def _via_gateway(token, is_api_key, state, questions, timeout):
    body = _post(
        _GATEWAY_URL,
        {
            "Authorization": f"Bearer {token}",
            "ai-gateway-protocol-version": "0.0.1",
            "ai-gateway-auth-method": "api-key" if is_api_key else "oidc",
            "ai-evaluation-model-specification-version": "4",
            "ai-model-id": "typesafe-ai/jev",
        },
        {"state": state, "questions": questions},
        timeout,
    )
    answers = body["answers"]
    confidence = ((body.get("providerMetadata") or {}).get("typesafe") or {}).get("confidence") or {}
    for key, answer in answers.items():
        if answer.get("type") in ("choice", "score"):
            answer["confidence"] = float(confidence.get(key, 0.0))
    return answers


def evaluate(state, questions, timeout=8.0, assets=None):
    """One request, all questions answered in parallel. Returns {question_id: answer} or None."""
    global _warned
    if os.environ.get("JEV_DISABLED") == "1":
        return None
    typesafe_key = os.environ.get("TYPESAFE_API_KEY")
    gateway_key = os.environ.get("AI_GATEWAY_API_KEY")
    gateway_token = gateway_key or os.environ.get("VERCEL_OIDC_TOKEN")
    if not typesafe_key and not gateway_token:
        return None
    if assets and not typesafe_key:  # the gateway has no image support
        return None
    try:
        if typesafe_key:
            return _via_typesafe(typesafe_key, state, questions, timeout, assets)
        return _via_gateway(gateway_token, bool(gateway_key), state, questions, timeout)
    except Exception as e:  # noqa: BLE001 — advisory call, must never break the crawler
        if not _warned:  # one line per process, not one per row
            _warned = True
            # ASCII only: a cp949 console must not turn this warning into a UnicodeEncodeError.
            print(f"  [jev] unavailable, using existing behaviour: {ascii(str(e)[:120])}")
        return None


if __name__ == "__main__":
    # Self-check: fallback paths need no network; the live call runs only when a key is present.
    names = ("TYPESAFE_API_KEY", "AI_GATEWAY_API_KEY", "VERCEL_OIDC_TOKEN")
    saved = {k: os.environ.pop(k, None) for k in names}
    assert evaluate({"x": "y"}, {"q": {"type": "boolean", "instructions": "?"}}) is None, "no key -> None"
    os.environ.update({k: v for k, v in saved.items() if v})
    os.environ["JEV_DISABLED"] = "1"
    assert evaluate({"x": "y"}, {"q": {"type": "boolean", "instructions": "?"}}) is None, "disabled -> None"
    del os.environ["JEV_DISABLED"]
    live = evaluate(
        {"title": "아이폰 17 프로 투명 케이스 맥세이프"},
        {
            "accessory": {"type": "boolean", "instructions": "Is `title` a listing for a phone accessory rather than a phone?"},
            "kind": {"type": "choice", "instructions": "What is `title` selling?",
                     "criteria": {"phone": "a handset", "accessory": "a case, film, charger or other accessory"}},
        },
    )
    if live:
        assert live["accessory"]["type"] == "boolean" and 0.0 <= live["accessory"]["probability"] <= 1.0
        assert live["kind"]["choice"] in ("phone", "accessory") and "confidence" in live["kind"]
    print("fallback paths OK; live:", json.dumps(live, ensure_ascii=False) if live else "skipped/unavailable")
