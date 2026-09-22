import json
from decimal import Decimal
from unittest.mock import patch

import pytest

from frontier_diplomacy.accounting import CostLedger, PriceSnapshot, BudgetExceeded
from frontier_diplomacy.telemetry import CallAccounting


@pytest.mark.parametrize('provider,client_name,usage,expected', [
    ('openrouter', 'OpenRouterClient', {'prompt_tokens': 1000, 'completion_tokens': 500,
        'completion_tokens_details': {'reasoning_tokens': 200}, 'cost': 0.002}, (1000, 300, 200, 0)),
    ('google', 'GeminiClient', {'prompt_token_count': 1000, 'candidates_token_count': 300,
        'thoughts_token_count': 200, 'cached_content_token_count': 100}, (1000, 300, 200, 100)),
    ('google', 'GeminiClient', {'prompt_token_count': 1000, 'candidates_token_count': 300,
        'total_token_count': 1500}, (1000, 300, 200, 0)),
    ('anthropic', 'ClaudeClient', {'input_tokens': 900, 'output_tokens': 500,
        'cache_read_input_tokens': 100}, (1000, 500, 0, 100)),
    ('xai', 'XAIClient', {'prompt_tokens': 1000, 'completion_tokens': 300,
        'completion_tokens_details': {'reasoning_tokens': 200},
        'cost_in_usd_ticks': 20000000}, (1000, 300, 200, 0)),
])
def test_provider_usage_is_normalized_once(tmp_path, provider, client_name, usage, expected):
    path = tmp_path / 'costs.sqlite'
    ledger = CostLedger(path)
    ledger.add_price(PriceSnapshot('model', provider, Decimal('1'), Decimal('2')))
    ledger.set_budget('test', Decimal('1'))
    client = type(client_name, (), dict(model_name='model', system_prompt='', max_tokens=1000))()
    with patch.dict('os.environ', FRONTIER_LEDGER_PATH=str(path), FRONTIER_EXPERIMENT_ID='test'):
        accounting = CallAccounting(client, 'hello', 'FRANCE', 'S1901M', 'order')
        accounting.reserve()
        accounting.dispatch()
        client.last_usage = usage
        accounting.finish('success')
    with ledger._connection() as con:
        row = con.execute('SELECT * FROM usage_records').fetchone()
    assert tuple(row[k] for k in ('input_tokens', 'output_tokens', 'reasoning_tokens', 'cached_input_tokens')) == expected
    assert Decimal(row['reported_cost_usd'] or row['calculated_cost_usd']) == Decimal('0.002')
    assert json.loads(row['raw_usage'])['_measurement']['request_ms'] is not None
    assert ledger.budget_state('test')['reserved_usd'] == 0


def test_missing_usage_retains_exposure_and_does_not_reuse_last_call(tmp_path):
    path = tmp_path / 'costs.sqlite'
    ledger = CostLedger(path)
    ledger.add_price(PriceSnapshot('model', 'openai', Decimal('1'), Decimal('2')))
    ledger.set_budget('test', Decimal('0.01'))
    client = type('OpenAIClient', (), dict(model_name='model', system_prompt='', max_tokens=1000,
                                          last_usage={'prompt_tokens': 999}))()
    with patch.dict('os.environ', FRONTIER_LEDGER_PATH=str(path), FRONTIER_EXPERIMENT_ID='test'):
        accounting = CallAccounting(client, 'hello', 'FRANCE', 'S1901M', 'order')
        accounting.reserve()
        accounting.dispatch()
        assert client.last_usage is None
        accounting.finish('unknown')
    state = ledger.budget_state('test')
    assert state['spent_usd'] == 0
    assert state['reserved_usd'] > 0
    with pytest.raises(BudgetExceeded):
        ledger.reserve('test', 'next', Decimal('0.01'))
