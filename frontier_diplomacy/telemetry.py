"""Optional provider-call accounting bridge used inside the legacy game process."""

from decimal import Decimal
import os
import time
import uuid
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from .accounting import BudgetExceeded, CostLedger, UsageRecord


def _provider(client: Any) -> str:
    name = type(client).__name__.lower()
    if "xai" in name:
        return "xai"
    if "claude" in name or "anthropic" in name:
        return "anthropic"
    if "gemini" in name:
        return "google"
    if "deepseek" in name:
        return "deepseek"
    if "together" in name:
        return "together"
    if "router" in name or "request" in name:
        return "openrouter"
    return "openai" if "openai" in name else "unknown"


def _value(source: Any, *names: str) -> int:
    for name in names:
        value = getattr(source, name, None) if not isinstance(source, dict) else source.get(name)
        if value is not None:
            return int(value)
    return 0


def google_reasoning_tokens(raw: dict) -> int:
    """Older Gemini SDKs drop thoughtsTokenCount but retain totalTokenCount.

    Google's documented total = prompt + thoughts + candidates. The fallback
    derives a category from provider-reported totals, never from response text.
    """
    if raw.get("thoughts_token_count") is not None:
        return _value(raw, "thoughts_token_count")
    return max(0, _value(raw, "total_token_count") - _value(raw, "prompt_token_count")
               - _value(raw, "candidates_token_count"))


class CallAccounting:
    """Context manager-style object that reserves then records one model call."""

    def __init__(self, client: Any, prompt: str, power: str | None, phase: str, task: str):
        self.client, self.prompt, self.power, self.phase, self.task = client, prompt, power, phase, task
        self.path = os.environ.get("FRONTIER_LEDGER_PATH")
        self.experiment_id = os.environ.get("FRONTIER_EXPERIMENT_ID")
        self.game_id = os.environ.get("FRONTIER_GAME_ID")
        self.request_id = str(uuid.uuid4())
        self.started = time.monotonic()
        self.reservation_id: str | None = None
        self.ledger: CostLedger | None = CostLedger(self.path) if self.path and self.experiment_id else None
        self.provider = _provider(client)
        self.price = None
        self.dispatched = None
        self.queue_ms = None

    def _trace(self, event: str, **details: Any) -> None:
        path = os.environ.get("FRONTIER_TRACE_PATH")
        if path:
            with Path(path).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"event": event, "at": datetime.now(timezone.utc).isoformat(),
                    "request_id": self.request_id, "provider": self.provider, "model": self.client.model_name,
                    "power": self.power, "phase": self.phase, "task": self.task, **details}, default=str) + "\n")

    def reserve(self) -> None:
        if not self.ledger:
            return
        price = self.ledger.latest_price(self.client.model_name, self.provider)
        if not price:
            raise RuntimeError(f"missing price snapshot for {self.provider}:{self.client.model_name}")
        self.price = price
        if self.provider == "openrouter":
            self.client.budget_provider_options = {
                "require_parameters": True,
                "max_price": {"prompt": float(price.input_per_million), "completion": float(price.output_per_million)},
            }
        # Text-only bound: one token per UTF-8 byte, plus random prefix,
        # message framing and client suffix. No chars/3 average authorizes spend.
        input_tokens = len(self.prompt.encode("utf-8")) + len(getattr(self.client, "system_prompt", "").encode("utf-8")) + 1024
        max_output = int(getattr(self.client, "max_tokens", 0))
        # Refuse a long-context request until tier-aware reservations exist.
        if input_tokens >= 200000:
            raise BudgetExceeded("input bound crosses a pricing tier; explicit tier pricing required")
        record = UsageRecord(self.request_id, self.experiment_id, self.game_id, self.power, self.phase, self.task,
                             self.client.model_name, self.provider, input_tokens=input_tokens, output_tokens=max_output)
        self.reservation_id = self.ledger.reserve(self.experiment_id, self.request_id, price.calculated_cost(record))

    def dispatch(self) -> None:
        self.dispatched = time.monotonic()
        self.queue_ms = int((self.dispatched - self.started) * 1000)
        self.client.last_usage = None
        self.client.last_response_metadata = None
        self._trace("dispatched", queue_ms=self.queue_ms)

    def finish(self, outcome: str) -> None:
        if not self.ledger:
            return
        raw = dict(getattr(self.client, "last_usage", None) or {})
        has_usage = bool(raw)
        prompt = _value(raw, "prompt_tokens", "input_tokens", "prompt_token_count")
        output = _value(raw, "completion_tokens", "output_tokens", "candidates_token_count")
        details = raw.get("prompt_tokens_details") or {}
        completion_details = raw.get("completion_tokens_details") or {}
        cached = _value(details, "cached_tokens")
        cache_write = _value(details, "cache_write_tokens")
        reasoning = _value(completion_details, "reasoning_tokens")
        # Ledger output excludes reasoning; OpenAI-compatible totals include it.
        if "completion_tokens" in raw and self.provider != "xai":
            output = max(0, output - reasoning)
        if self.provider == "google":
            cached = _value(raw, "cached_content_token_count")
            reasoning = google_reasoning_tokens(raw)
            if "thoughts_token_count" not in raw and reasoning:
                raw["_reasoning_normalization"] = "derived: total_token_count - prompt_token_count - candidates_token_count"
        if self.provider == "anthropic":
            cached = _value(raw, "cache_read_input_tokens")
            cache_write = _value(raw, "cache_creation_input_tokens")
            prompt += cached + cache_write
        raw["_measurement"] = {
            "version": 2, "queue_ms": self.queue_ms,
            "request_ms": int((time.monotonic() - self.dispatched) * 1000) if self.dispatched else None,
            "prompt_bytes": len(self.prompt.encode("utf-8")),
            "max_output_tokens": getattr(self.client, "max_tokens", None),
            "response": getattr(self.client, "last_response_metadata", None),
        }
        reported = raw.get("cost") if isinstance(raw, dict) else None
        if self.provider == "xai" and raw.get("cost_in_usd_ticks") is not None:
            reported = Decimal(str(raw["cost_in_usd_ticks"])) / Decimal("10000000000")
        price = self.price
        record = UsageRecord(self.request_id, self.experiment_id, self.game_id, self.power, self.phase, self.task,
                             self.client.model_name, self.provider, prompt, output, cached, cache_write, reasoning,
                             int((time.monotonic() - self.started) * 1000), outcome,
                             reported_cost_usd=Decimal(str(reported)) if reported is not None else None,
                             certainty="reported" if reported is not None else "calculated" if has_usage else "unknown",
                             pricing_snapshot_id=price.id if price else None, raw_usage=raw if isinstance(raw, dict) else None)
        if price and record.reported_cost_usd is None and has_usage:
            record = UsageRecord(**{**record.__dict__, "calculated_cost_usd": price.calculated_cost(record)})
        self.ledger.reconcile(self.reservation_id, record, unresolved=outcome == "unknown" or not has_usage) if self.reservation_id else self.ledger.record_usage(record)
        self._trace("finished", outcome=outcome, measurement=raw["_measurement"], certainty=record.certainty)
