"""Papago 번역 (네이버클라우드 AI·NAVER API > Papago Translation). 다국어 메뉴판에 쓴다.

POST https://papago.apigw.ntruss.com/nmt/v1/translation
  헤더  X-NCP-APIGW-API-KEY-ID: <Client ID>, X-NCP-APIGW-API-KEY: <Client Secret>, Content-Type: application/json
  본문  {"source": "ko", "target": "en" | "ja" | "zh-CN", "text": "...(5,000자까지)"}
  응답  {"message": {"result": {"translatedText": "..."}}}
(공식 문서 https://api.ncloud-docs.com/docs/ai-naver-papagonmt-translation 로 11/15 확인. 실제 호출은 아직 못 해 봄)

- 키: PAPAGO_CLIENT_ID, PAPAGO_CLIENT_SECRET (서버 환경 파일에만. 저장소에 넣지 않음). 없으면 available=False → 부르지 않음.
- 같은 글은 한 번만 번역하고 data/runtime/translations.json 에 저장해 다시 쓴다 (비용·속도, 같은 메뉴가 매번 다르게 번역되는 일 방지).
- 사용 기록(logs/llm_usage.jsonl)에는 글자 수·시간·상태만. 번역할 글은 남기지 않는다.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime

import httpx

from app.sources import capture

log = logging.getLogger("review_insight.papago")
ENDPOINT = "https://papago.apigw.ntruss.com/nmt/v1/translation"
LANGS = ("en", "ja", "zh-CN")
_lock = threading.Lock()


class TranslateError(Exception):
    pass


class Papago:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None,
                 transport: httpx.BaseTransport | None = None, timeout: float | None = None):
        env = os.environ
        self.client_id = (client_id if client_id is not None else env.get("PAPAGO_CLIENT_ID", "")).strip()
        self.client_secret = (client_secret if client_secret is not None else env.get("PAPAGO_CLIENT_SECRET", "")).strip()
        self.timeout = float(timeout if timeout is not None else (env.get("PAPAGO_TIMEOUT_SECONDS", "") or 10))
        self.transport = transport

    @property
    def available(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _cache_file(self):
        from app import service
        return service.RUNTIME / "translations.json"

    def _cache(self) -> dict:
        try:
            return json.loads(self._cache_file().read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def translate(self, text: str, target: str, source: str = "ko") -> str:
        """번역 1건. 저장본이 있으면 그것을, 없으면 Papago 를 부른다. 키가 없으면 TranslateError."""
        text = " ".join((text or "").split())
        if not text:
            return ""
        if target not in LANGS + ("ko",):
            raise TranslateError(f"지원하지 않는 언어: {target}")
        key = f"{source}>{target}:{text}"
        with _lock:
            hit = self._cache().get(key)
        if hit is not None:
            return hit
        if not self.available:
            raise TranslateError("Papago 키가 없습니다 (PAPAGO_CLIENT_ID, PAPAGO_CLIENT_SECRET)")
        out = self._call(text, source, target)
        with _lock:
            cache = self._cache()
            cache[key] = out
            path = self._cache_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(path)
        return out

    def _call(self, text: str, source: str, target: str) -> str:
        t0, resp, status = time.perf_counter(), None, "ok"
        for attempt in range(2):          # 429·5xx·시간 초과만 한 번 더
            try:
                with httpx.Client(timeout=self.timeout, transport=self.transport) as c:
                    resp = c.post(ENDPOINT, json={"source": source, "target": target, "text": text}, headers={
                        "X-NCP-APIGW-API-KEY-ID": self.client_id, "X-NCP-APIGW-API-KEY": self.client_secret,
                        "Content-Type": "application/json"})
            except httpx.TimeoutException:
                resp, status = None, "TRANSLATE_TIMEOUT"
                continue
            if (resp.status_code == 429 or resp.status_code >= 500) and attempt == 0:
                continue
            break
        out = ""
        if resp is not None:
            if resp.status_code == 200:
                out = ((((resp.json() or {}).get("message") or {}).get("result") or {}).get("translatedText") or "").strip()
                status = "ok" if out else "TRANSLATE_EMPTY"
            else:
                status = "TRANSLATE_RATE_LIMITED" if resp.status_code == 429 else "TRANSLATE_UPSTREAM_ERROR"
        row = {"ts": datetime.now(capture.KST).isoformat(timespec="seconds"), "purpose": "menu_translate", "model": "papago",
               "http_status": resp.status_code if resp is not None else None, "status": status, "chars": len(text),
               "target": target, "latency_ms": int((time.perf_counter() - t0) * 1000)}
        try:
            capture.USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with capture.USAGE_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("사용량 기록 실패: %s", e)
        if status != "ok":
            raise TranslateError(status)
        return out
