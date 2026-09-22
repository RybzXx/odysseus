"""
A scripted stand-in for 9router, for the Layer Two tests. No network.

FakeGateway answers each task by the marker its prompt carries. A test swaps
one answer (e.g. a caption line with a price in it) or makes every call fail,
and counts calls to prove a step did or did not reach Layer Two.
"""
import json

import httpx

from mahdawi.layer2.gateway import Gateway, GatewayUnavailable


def _facts(messages):
    text = messages[-1]["content"]
    if isinstance(text, list):
        return {}
    return json.loads(text.split("FACTS:\n", 1)[1])


class FakeGateway(Gateway):
    def __init__(self, **answers):
        super().__init__("http://fake/v1")
        self.down = False
        self.calls = []
        self.answers = {
            "note": json.dumps({"buyer": "العوائل ببغداد", "season": "طول السنة",
                                "angle": "عملي للبيت"}),
            "line": "خوش اختيار للبيت، عملي وسهل الاستعمال.",
            "image": json.dumps({"ok": True, "reasons": []}),
            "classify": json.dumps({"intent": "price", "tier_signal": "FAQ_TIER",
                                    "tone": "neutral", "confidence": 0.95,
                                    "reasoning": "price question"}),
            "reply": "هلا بيك، السعر مكتوب بالبوست.",
        }
        self.answers.update(answers)

    def complete(self, model, messages, **kwargs):
        if self.down:
            raise GatewayUnavailable("ConnectError: 9router is down")
        body = messages[-1]["content"]
        text = body[0]["text"] if isinstance(body, list) else body
        if "Research note" in text:
            kind = "note"
        elif "ONE selling line" in text:
            kind = "line"
        elif "Check this product image" in text:
            kind = "image"
        elif "Rank the products" in text:
            kind = "rank"
        elif "Classify it" in text:
            kind = "classify"
        else:
            kind = "reply"
        self.calls.append(kind)
        if kind == "rank" and "rank" not in self.answers:
            skus = [p["sku"] for p in _facts(messages)["products"]]
            return json.dumps([{"sku": s, "rank": i + 1, "reason": "طلب عالي"}
                               for i, s in enumerate(sorted(skus))])
        answer = self.answers[kind]
        return answer(messages) if callable(answer) else answer


def http_post(status=200, content="نص", exc=None):
    """A fake httpx.post for the real Gateway."""
    def post(url, json=None, headers=None, timeout=None):
        if exc:
            raise exc
        return httpx.Response(status, json={"choices": [{"message": {"content": content}}]},
                              request=httpx.Request("POST", url))
    return post
