"""Optional provider-call accounting bridge used inside the legacy game process."""

from decimal import Decimal
import os
import time
import uuid
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

    def reserve(self) -> None:
        if not self.ledger:
            return
        price = self.ledger.latest_price(self.client.model_name, self.provider)
        if not price:
            raise RuntimeError(f"missing price snapshot for {self.provider}:{self.client.model_name}")
        # Conservative local input bound; output is bounded by the configured
        # API maximum. The reservation is reconciled to actual usage later.
        input_tokens = (len(self.prompt) + len(getattr(self.client, "system_prompt", ""))) // 3 + 1
        max_output = int(getattr(self.client, "max_tokens", 0))
        record = UsageRecord(self.request_id, self.experiment_id, self.game_id, self.power, self.phase, self.task,
                             self.client.model_name, self.provider, input_tokens=input_tokens, output_tokens=max_output)
        self.reservation_id = self.ledger.reserve(self.experiment_id, self.request_id, price.calculated_cost(record))

    def finish(self, outcome: str) -> None:
        if not self.ledger:
            return
        raw = getattr(self.client, "last_usage", None) or {}
        prompt = _value(raw, "prompt_tokens", "input_tokens")
        output = _value(raw, "completion_tokens", "output_tokens", "candidates_token_count")
        details = raw.get("prompt_tokens_details", {}) if isinstance(raw, dict) else {}
        completion_details = raw.get("completion_tokens_details", {}) if isinstance(raw, dict) else {}
        cached = _value(details, "cached_tokens")
        cache_write = _value(details, "cache_write_tokens")
        reasoning = _value(completion_details, "reasoning_tokens")
        reported = raw.get("cost") if isinstance(raw, dict) else None
        price = self.ledger.latest_price(self.client.model_name, self.provider)
        record = UsageRecord(self.request_id, self.experiment_id, self.game_id, self.power, self.phase, self.task,
                             self.client.model_name, self.provider, prompt, output, cached, cache_write, reasoning,
                             int((time.monotonic() - self.started) * 1000), outcome,
                             reported_cost_usd=Decimal(str(reported)) if reported is not None else None,
                             certainty="reported" if reported is not None else "calculated" if raw else "unknown",
                             pricing_snapshot_id=price.id if price else None, raw_usage=raw if isinstance(raw, dict) else None)
        if price and record.reported_cost_usd is None and raw:
            record = UsageRecord(**{**record.__dict__, "calculated_cost_usd": price.calculated_cost(record)})
        self.ledger.reconcile(self.reservation_id, record, unresolved=outcome == "unknown") if self.reservation_id else self.ledger.record_usage(record)
