"""
layer2.gateway — the one door from Layer One to 9router.

An OpenAI-compatible chat call, and nothing else. It deliberately does not
reuse src.llm_core.llm_call: that path caches every response by its input, so
a retry after a rejected output would return the same rejected text forever.

Failure has one shape. Every way a call can go wrong — connection refused, a
timeout, a non-200 status, an empty answer, JSON that does not parse, output
that fails its code check — raises a Layer2Failure. Callers catch that one
class and leave the item waiting; nothing here returns a substitute answer.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

import httpx

from mahdawi.layer2 import settings

# A check returns None when the output is usable, or a reason when it is not.
OutputCheck = Callable[[Any], Optional[str]]


class Layer2Failure(RuntimeError):
    """A Layer Two step produced nothing usable. The item must wait."""


class GatewayUnavailable(Layer2Failure):
    """9router did not answer, or answered with an error."""


class OutputRejected(Layer2Failure):
    """9router answered, and a code check refused the answer."""


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def chat_url(base_url: str) -> str:
    """
    Pre : base_url is the endpoint's base, e.g. http://localhost:20128/v1.
    Post: the chat-completions URL, whether or not base_url already names it.
    """
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


class Gateway:
    """
    Pre : url is the 9router base URL, or None when no enabled 9router endpoint
          exists. headers carry any auth the endpoint row holds; this module
          never reads or stores a key itself.
    Invariant: complete() returns non-empty text or raises Layer2Failure.
    """

    def __init__(self, url: Optional[str], headers: Optional[Dict[str, str]] = None,
                 timeout: float = settings.TIMEOUT_SECONDS,
                 post: Optional[Callable[..., httpx.Response]] = None):
        self.url = chat_url(url) if url else None
        self.headers = dict(headers or {})
        self.timeout = timeout
        self._post = post or httpx.post

    def complete(self, model: str, messages: List[dict],
                 max_tokens: int = settings.MAX_TOKENS,
                 temperature: float = 0.4) -> str:
        if self.url is None:
            raise GatewayUnavailable("no enabled 9router endpoint")
        # stream must be explicit: 9router answers with an SSE stream when the
        # field is absent (observed 2026-09-22), which this parser cannot read.
        payload = {"model": model, "messages": messages, "stream": False,
                   "max_tokens": max_tokens, "temperature": temperature}
        try:
            resp = self._post(self.url, json=payload, headers=self.headers,
                              timeout=self.timeout)
        except Exception as exc:
            raise GatewayUnavailable("%s: %s" % (exc.__class__.__name__, exc)) from exc
        if resp.status_code != 200:
            raise GatewayUnavailable("HTTP %d: %s" % (resp.status_code, resp.text[:200]))
        try:
            text = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            raise GatewayUnavailable("unexpected response shape") from exc
        if not isinstance(text, str) or not text.strip():
            raise GatewayUnavailable("empty answer")
        return text.strip()

    def complete_text(self, model: str, messages: List[dict], check: OutputCheck,
                      clean: Optional[Callable[[str], str]] = None, **kwargs) -> str:
        """
        Post: text that check() accepted — after clean(), when given, so the
              text checked is exactly the text returned.
        Raises: OutputRejected naming check()'s reason.
        """
        text = self.complete(model, messages, **kwargs)
        if clean is not None:
            text = clean(text)
        problem = check(text)
        if problem:
            raise OutputRejected(problem)
        return text

    def complete_json(self, model: str, messages: List[dict], check: OutputCheck,
                      **kwargs) -> Any:
        """
        Post: a parsed JSON value that check() accepted.
        Raises: OutputRejected when the answer is not JSON or check() refuses it.
        """
        text = self.complete(model, messages, **kwargs)
        try:
            data = json.loads(_FENCE.sub("", text.strip()))
        except ValueError as exc:
            raise OutputRejected("answer is not JSON") from exc
        problem = check(data)
        if problem:
            raise OutputRejected(problem)
        return data
