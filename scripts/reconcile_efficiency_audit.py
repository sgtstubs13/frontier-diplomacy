"""Append auditable corrections for this audit's early v2 accounting records.

No provider calls and no edits to historical records. Safe to repeat.
"""
from pathlib import Path
import sys
import json
from decimal import Decimal
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frontier_diplomacy.accounting import CostLedger, PriceSnapshot, UsageRecord
from frontier_diplomacy.telemetry import google_reasoning_tokens

EXPERIMENT = 'efficiency-audit-20260922-d54ea8d8'


def reconcile():
    ledger = CostLedger()
    price = ledger.latest_price('gpt-5.6-terra', 'openai')
    if price.input_per_million != Decimal('2') or price.output_per_million != Decimal('12'):
        price = ledger.add_price(PriceSnapshot('gpt-5.6-terra','openai',Decimal('2'),Decimal('12'),
            Decimal('0.2'),Decimal('2.5'),'https://developers.openai.com/api/docs/pricing'))
    with ledger._connection() as con:
        rows = con.execute("SELECT * FROM usage_records WHERE experiment_id=? AND task != 'accounting_adjustment'", (EXPERIMENT,)).fetchall()
    for row in rows:
        raw = json.loads(row['raw_usage'] or '{}')
        if row['provider'] == 'xai' and raw.get('cost_in_usd_ticks') is not None:
            correct = Decimal(str(raw['cost_in_usd_ticks'])) / Decimal('10000000000')
            reason = 'xAI reported ticks; completion_tokens excludes reasoning'
        elif row['provider'] == 'openai' and row['model_id'] == 'gpt-5.6-terra':
            usage = UsageRecord('calculation',EXPERIMENT,None,None,None,'order',row['model_id'],'openai',
                input_tokens=row['input_tokens'],output_tokens=row['output_tokens'],
                reasoning_tokens=row['reasoning_tokens'],cached_input_tokens=row['cached_input_tokens'],
                cache_write_tokens=row['cache_write_tokens'])
            correct = price.calculated_cost(usage)
            reason = 'standard API rates; original card incorrectly used batch rates'
        elif row['provider'] == 'google' and 'thoughts_token_count' not in raw:
            historical = next(p for p in ledger.prices() if p.id == row['pricing_snapshot_id'])
            missing_thoughts = google_reasoning_tokens(raw) - row['reasoning_tokens']
            correct = Decimal(row['calculated_cost_usd']) + Decimal(missing_thoughts) * historical.output_per_million / Decimal('1000000')
            reason = 'Gemini SDK omitted thoughts count; derived from documented total minus prompt minus candidates'
        else:
            continue
        previous = Decimal(row['reported_cost_usd'] or row['calculated_cost_usd'] or '0')
        delta = correct - previous
        if delta == 0:
            continue
        ledger.record_usage(UsageRecord(row['request_id']+'-accounting-adjustment',EXPERIMENT,row['game_id'],row['power'],row['phase'],
            'accounting_adjustment',row['model_id'],row['provider'],outcome='adjustment',
            calculated_cost_usd=delta,certainty='audited_adjustment',raw_usage={
                'original_request_id':row['request_id'],'reason':reason,'correct_total_usd':str(correct)}))
    print(ledger.budget_state(EXPERIMENT))


if __name__ == '__main__':
    reconcile()
