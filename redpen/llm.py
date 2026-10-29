"""Thin wrapper around Token Factory chat completions.

Every call is recorded in a Ledger (model, tokens, latency, cost) so the UI can show
exactly which Nemotron model did which step and what it cost.
"""

import json
import re
import time
from dataclasses import asdict, dataclass, field

from . import config


@dataclass
class Call:
    step: str
    model: str
    seconds: float
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


@dataclass
class Ledger:
    calls: list[Call] = field(default_factory=list)

    def add(self, step: str, model: str, seconds: float, usage) -> None:
        p = getattr(usage, "prompt_tokens", 0) or 0
        c = getattr(usage, "completion_tokens", 0) or 0
        price_in, price_out = config.PRICES.get(model, (0.0, 0.0))
        cost = (p * price_in + c * price_out) / 1_000_000
        self.calls.append(Call(step, model, round(seconds, 2), p, c, round(cost, 6)))

    def to_list(self) -> list[dict]:
        return [asdict(c) for c in self.calls]


class ModelError(RuntimeError):
    pass


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def extract_json(text: str) -> dict:
    """Parse the first JSON object in a model reply, tolerating code fences and stray prose."""
    text = _THINK_RE.sub("", text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def chat_json(
    step: str,
    model: str,
    messages: list[dict],
    ledger: Ledger,
    *,
    thinking: bool = False,
    max_tokens: int = 4000,
    attempts: int = 2,
) -> dict:
    """Call a model and return its reply parsed as JSON, retrying once on malformed output."""
    last_error: Exception | None = None
    for _ in range(attempts):
        started = time.time()
        try:
            response = config.client().chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.1,
                response_format={"type": "json_object"},
                extra_body={"chat_template_kwargs": {"enable_thinking": thinking}},
            )
        except Exception as e:  # network / API errors already retried by the SDK
            raise ModelError(f"{step}: {model} request failed: {e}") from e
        ledger.add(step, model, time.time() - started, response.usage)
        try:
            return extract_json(response.choices[0].message.content)
        except (json.JSONDecodeError, TypeError) as e:
            last_error = e
    raise ModelError(f"{step}: {model} did not return valid JSON ({last_error})")
