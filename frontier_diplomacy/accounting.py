"""Durable local usage ledger, cost forecasts, and budget reservations."""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import sqlite3
import uuid
from typing import Any, Iterator

MILLION = Decimal("1000000")
MONEY = Decimal("0.000001")


def _money(value: Decimal | str | int | float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PriceSnapshot:
    model_id: str
    provider: str
    input_per_million: Decimal
    output_per_million: Decimal
    cached_input_per_million: Decimal | None = None
    cache_write_per_million: Decimal | None = None
    source: str = "manual"
    effective_at: str = ""
    service_tier: str = "standard"
    id: int | None = None

    def calculated_cost(self, usage: "UsageRecord") -> Decimal:
        normal_input = max(0, usage.input_tokens - usage.cached_input_tokens - usage.cache_write_tokens)
        value = Decimal(normal_input) * self.input_per_million / MILLION
        value += Decimal(usage.output_tokens + usage.reasoning_tokens) * self.output_per_million / MILLION
        if self.cached_input_per_million is not None:
            value += Decimal(usage.cached_input_tokens) * self.cached_input_per_million / MILLION
        if self.cache_write_per_million is not None:
            value += Decimal(usage.cache_write_tokens) * self.cache_write_per_million / MILLION
        return _money(value) or Decimal("0")


@dataclass(frozen=True)
class UsageRecord:
    request_id: str
    experiment_id: str | None
    game_id: str | None
    power: str | None
    phase: str | None
    task: str
    model_id: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    latency_ms: int | None = None
    outcome: str = "success"
    reported_cost_usd: Decimal | None = None
    calculated_cost_usd: Decimal | None = None
    certainty: str = "unknown"
    pricing_snapshot_id: int | None = None
    raw_usage: dict[str, Any] | None = None
    created_at: str = ""

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        for key in ("reported_cost_usd", "calculated_cost_usd"):
            row[key] = str(row[key]) if row[key] is not None else None
        row["raw_usage"] = json.dumps(row["raw_usage"], sort_keys=True) if row["raw_usage"] else None
        return row


@dataclass(frozen=True)
class CostEstimate:
    expected_usd: Decimal
    low_usd: Decimal
    high_usd: Decimal
    full_duration_usd: Decimal
    confidence: str
    comparable_calls: int
    assumptions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {**{key: str(value) for key, value in asdict(self).items() if key.endswith("usd")},
                "confidence": self.confidence, "comparable_calls": self.comparable_calls,
                "assumptions": list(self.assumptions)}


class CostLedger:
    """SQLite ledger designed to survive individual experiment directories."""

    def __init__(self, path: str | Path = "data/frontier_diplomacy_costs.sqlite"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS price_snapshots (
              id INTEGER PRIMARY KEY, model_id TEXT NOT NULL, provider TEXT NOT NULL,
              input_per_million TEXT NOT NULL, output_per_million TEXT NOT NULL,
              cached_input_per_million TEXT, cache_write_per_million TEXT,
              source TEXT NOT NULL, effective_at TEXT NOT NULL, service_tier TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS usage_records (
              request_id TEXT PRIMARY KEY, experiment_id TEXT, game_id TEXT, power TEXT,
              phase TEXT, task TEXT NOT NULL, model_id TEXT NOT NULL, provider TEXT NOT NULL,
              input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
              cached_input_tokens INTEGER NOT NULL, cache_write_tokens INTEGER NOT NULL,
              reasoning_tokens INTEGER NOT NULL, latency_ms INTEGER, outcome TEXT NOT NULL,
              reported_cost_usd TEXT, calculated_cost_usd TEXT, certainty TEXT NOT NULL,
              pricing_snapshot_id INTEGER, raw_usage TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reservations (
              id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, request_id TEXT NOT NULL,
              amount_usd TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL,
              resolved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS budget_events (
              id INTEGER PRIMARY KEY, experiment_id TEXT NOT NULL, budget_usd TEXT NOT NULL,
              event TEXT NOT NULL, created_at TEXT NOT NULL, note TEXT
            );
            CREATE INDEX IF NOT EXISTS usage_model_task ON usage_records(model_id, provider, task);
            CREATE INDEX IF NOT EXISTS usage_experiment ON usage_records(experiment_id);
            CREATE INDEX IF NOT EXISTS reservation_experiment ON reservations(experiment_id, state);
            """)

    def add_price(self, price: PriceSnapshot) -> PriceSnapshot:
        effective = price.effective_at or datetime.now(timezone.utc).isoformat()
        with self._connection() as con:
            cursor = con.execute("""INSERT INTO price_snapshots
              (model_id,provider,input_per_million,output_per_million,cached_input_per_million,cache_write_per_million,source,effective_at,service_tier)
              VALUES (?,?,?,?,?,?,?,?,?)""", (price.model_id, price.provider, str(price.input_per_million),
              str(price.output_per_million), str(price.cached_input_per_million) if price.cached_input_per_million is not None else None,
              str(price.cache_write_per_million) if price.cache_write_per_million is not None else None, price.source, effective, price.service_tier))
            return PriceSnapshot(**{**asdict(price), "effective_at": effective, "id": cursor.lastrowid})

    def latest_price(self, model_id: str, provider: str) -> PriceSnapshot | None:
        with self._connection() as con:
            row = con.execute("SELECT * FROM price_snapshots WHERE model_id=? AND provider=? ORDER BY effective_at DESC,id DESC LIMIT 1", (model_id, provider)).fetchone()
        if row is None:
            return None
        return PriceSnapshot(id=row["id"], model_id=row["model_id"], provider=row["provider"],
            input_per_million=Decimal(row["input_per_million"]), output_per_million=Decimal(row["output_per_million"]),
            cached_input_per_million=Decimal(row["cached_input_per_million"]) if row["cached_input_per_million"] else None,
            cache_write_per_million=Decimal(row["cache_write_per_million"]) if row["cache_write_per_million"] else None,
            source=row["source"], effective_at=row["effective_at"], service_tier=row["service_tier"])

    def prices(self) -> list[PriceSnapshot]:
        with self._connection() as con:
            rows = con.execute("SELECT * FROM price_snapshots ORDER BY effective_at DESC,id DESC").fetchall()
        return [PriceSnapshot(id=row["id"], model_id=row["model_id"], provider=row["provider"],
            input_per_million=Decimal(row["input_per_million"]), output_per_million=Decimal(row["output_per_million"]),
            cached_input_per_million=Decimal(row["cached_input_per_million"]) if row["cached_input_per_million"] else None,
            cache_write_per_million=Decimal(row["cache_write_per_million"]) if row["cache_write_per_million"] else None,
            source=row["source"], effective_at=row["effective_at"], service_tier=row["service_tier"]) for row in rows]

    def record_usage(self, record: UsageRecord) -> bool:
        row = record.to_row()
        row["created_at"] = row["created_at"] or datetime.now(timezone.utc).isoformat()
        with self._connection() as con:
            result = con.execute("""INSERT OR IGNORE INTO usage_records VALUES
              (:request_id,:experiment_id,:game_id,:power,:phase,:task,:model_id,:provider,:input_tokens,:output_tokens,
               :cached_input_tokens,:cache_write_tokens,:reasoning_tokens,:latency_ms,:outcome,:reported_cost_usd,
               :calculated_cost_usd,:certainty,:pricing_snapshot_id,:raw_usage,:created_at)""", row)
            return result.rowcount == 1

    def set_budget(self, experiment_id: str, budget: Decimal, note: str = "") -> None:
        with self._connection() as con:
            con.execute("INSERT INTO budget_events(experiment_id,budget_usd,event,created_at,note) VALUES(?,?,?,?,?)",
                        (experiment_id, str(_money(budget)), "set", datetime.now(timezone.utc).isoformat(), note))

    def budget_state(self, experiment_id: str) -> dict[str, Decimal]:
        with self._connection() as con:
            budget = con.execute("SELECT budget_usd FROM budget_events WHERE experiment_id=? ORDER BY id DESC LIMIT 1", (experiment_id,)).fetchone()
            if budget is None:
                raise ValueError("experiment has no budget")
            spent = con.execute("SELECT calculated_cost_usd,reported_cost_usd FROM usage_records WHERE experiment_id=?", (experiment_id,)).fetchall()
            reserved = con.execute("SELECT amount_usd FROM reservations WHERE experiment_id=? AND state='reserved'", (experiment_id,)).fetchall()
        actual = sum((Decimal(row["reported_cost_usd"] or row["calculated_cost_usd"] or "0") for row in spent), Decimal("0"))
        held = sum((Decimal(row["amount_usd"]) for row in reserved), Decimal("0"))
        limit = Decimal(budget["budget_usd"])
        return {"budget_usd": limit, "spent_usd": _money(actual) or Decimal("0"), "reserved_usd": _money(held) or Decimal("0"), "remaining_usd": _money(limit - actual - held) or Decimal("0")}

    def reserve(self, experiment_id: str, request_id: str, amount: Decimal) -> str:
        amount = _money(amount) or Decimal("0")
        with self._connection() as con:
            con.execute("BEGIN IMMEDIATE")
            budget = con.execute("SELECT budget_usd FROM budget_events WHERE experiment_id=? ORDER BY id DESC LIMIT 1", (experiment_id,)).fetchone()
            if budget is None:
                raise ValueError("a budget must be set before requests can be reserved")
            actual = sum((Decimal(row[0] or row[1] or "0") for row in con.execute("SELECT reported_cost_usd,calculated_cost_usd FROM usage_records WHERE experiment_id=?", (experiment_id,))), Decimal("0"))
            held = sum((Decimal(row[0]) for row in con.execute("SELECT amount_usd FROM reservations WHERE experiment_id=? AND state='reserved'", (experiment_id,))), Decimal("0"))
            if actual + held + amount > Decimal(budget["budget_usd"]):
                raise BudgetExceeded("budget cannot reserve the next request")
            reservation_id = str(uuid.uuid4())
            con.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?,NULL)", (reservation_id, experiment_id, request_id, str(amount), "reserved", datetime.now(timezone.utc).isoformat()))
            return reservation_id

    def reconcile(self, reservation_id: str, record: UsageRecord | None = None, unresolved: bool = False) -> None:
        if record is not None:
            self.record_usage(record)
        state = "unresolved" if unresolved else "reconciled"
        with self._connection() as con:
            con.execute("UPDATE reservations SET state=?,resolved_at=? WHERE id=? AND state='reserved'", (state, datetime.now(timezone.utc).isoformat(), reservation_id))

    def estimate(self, model_ids: list[tuple[str, str]], expected_calls: dict[tuple[str, str, str], int]) -> CostEstimate:
        expected = Decimal("0")
        comparable = 0
        assumptions: list[str] = []
        for model_id, provider in model_ids:
            price = self.latest_price(model_id, provider)
            if not price:
                raise ValueError(f"No current price snapshot for {provider}:{model_id}")
            for (call_model, call_provider, task), calls in expected_calls.items():
                if (call_model, call_provider) != (model_id, provider):
                    continue
                with self._connection() as con:
                    rows = con.execute("SELECT * FROM usage_records WHERE model_id=? AND provider=? AND task=? AND outcome='success'", (model_id, provider, task)).fetchall()
                comparable += len(rows)
                if rows:
                    unit_costs = [Decimal(row["reported_cost_usd"] or row["calculated_cost_usd"] or "0") for row in rows]
                    avg = sum(unit_costs, Decimal("0")) / len(unit_costs)
                    expected += avg * calls
                else:
                    assumptions.append(f"cold-start {provider}:{model_id}/{task}; uses max-output reservation")
        confidence = "high" if comparable >= 50 else "medium" if comparable >= 10 else "low"
        high = expected * (Decimal("1.5") if comparable else Decimal("2"))
        return CostEstimate(_money(expected) or Decimal("0"), _money(expected * Decimal("0.7")) or Decimal("0"),
                            _money(high) or Decimal("0"), _money(high) or Decimal("0"), confidence, comparable, tuple(assumptions))


class BudgetExceeded(BaseException):
    """Stops a worker promptly; it must not become a fallback order."""
    pass
