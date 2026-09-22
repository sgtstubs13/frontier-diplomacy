"""Explicitly launched, paid one-year diagnostic. Never imported by tests.

Run from the repository root with .venv/bin/python scripts/run_efficiency_audit.py.
Uses existing experiment/runner/ledger services; refuses to restart an existing run.
"""
import json
import os
from pathlib import Path
import sys
from dataclasses import replace, asdict
from decimal import Decimal
from datetime import datetime, timezone
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests
from dotenv import load_dotenv
from frontier_diplomacy.experiment import ExperimentConfig
from frontier_diplomacy.registry import LabRegistry
from frontier_diplomacy.service import ExperimentService
from frontier_diplomacy.runner import SeasonRunner, load_schedule
from frontier_diplomacy.models import POWERS
from frontier_diplomacy.doctor import check_registry

IDS = ('openai_gpt_5_6_terra', 'anthropic_claude_opus_4_7', 'google_gemini_3_8_flash',
       'meta_llama_4_maverick', 'deepseek_v4_1_flash', 'xai_grok_4_20', 'moonshot_kimi_k3')


def main():
    os.chdir(ROOT)
    load_dotenv(ROOT / '.env')
    registry = LabRegistry.from_file('config/labs.yaml')
    profiles = [registry.get(mid) for mid in IDS]
    profiles[0] = replace(profiles[0], metadata={**profiles[0].metadata, 'price': {
        'input_per_million': '2', 'output_per_million': '12', 'cached_input_per_million': '0.2',
        'cache_write_per_million': '2.5', 'source': 'https://developers.openai.com/api/docs/pricing',
    }})
    issues = check_registry(LabRegistry(profiles), require_keys=True)
    if issues:
        raise SystemExit('\n'.join(issues))
    response = requests.get('https://openrouter.ai/api/v1/models', timeout=30)
    response.raise_for_status()
    catalog = {row['id']: row for row in response.json()['data']}
    snapshots = {}
    for index, profile in enumerate(profiles):
        if profile.provider != 'openrouter':
            continue
        row = catalog[profile.model]
        snapshots[profile.model] = row
        rates = [row['pricing'], *row['pricing'].get('overrides', [])]
        # Reserve at the highest advertised time-of-day rate. Actual reported
        # OpenRouter charges remain authoritative on reconciliation.
        card = {
            'input_per_million': str(max(Decimal(rate['prompt']) for rate in rates) * 1000000),
            'output_per_million': str(max(Decimal(rate['completion']) for rate in rates) * 1000000),
            'source': 'https://openrouter.ai/api/v1/models',
        }
        if row['pricing'].get('input_cache_read') is not None:
            card['cached_input_per_million'] = str(Decimal(row['pricing']['input_cache_read']) * 1000000)
        profiles[index] = replace(profile, metadata={**profile.metadata, 'price': card})
    registry = LabRegistry(profiles)
    config = ExperimentConfig(name='efficiency-audit-20260922', model_ids=IDS, games=1, seed=20260922,
        max_year=1, negotiation_rounds=3, budget_usd=Decimal('5'),
        fixed_assignments=(dict(zip(POWERS, IDS)),), metadata={
            'purpose': 'Measured one-year baseline; optimization changes await approval',
            'output_limit': 16000, 'openrouter_concurrency': 1,
            'native_reasoning_settings': 'provider defaults; no effort override',
        })
    service = ExperimentService()
    details = service.create(config, registry)
    eid = details['experiment_id']
    directory = ROOT / 'results' / eid
    (directory / 'model_catalog.json').write_text(json.dumps(snapshots, indent=2) + '\n')
    (directory / 'profiles.json').write_text(json.dumps([asdict(p) for p in profiles], indent=2) + '\n')
    (directory / 'code.patch').write_text(subprocess.check_output(['git', 'diff'], text=True))
    (directory / 'run_start.json').write_text(json.dumps({'at': datetime.now(timezone.utc).isoformat(), 'pid': os.getpid()}) + '\n')
    print(json.dumps({'experiment': eid, 'assignments': config.fixed_assignments, 'budget': '5.00'}), flush=True)
    service._write_json(directory / 'status.json', {'status': 'running', 'experiment_id': eid})
    runner = SeasonRunner(registry, load_schedule(directory / 'schedule.json'), directory, ROOT, config)
    result = runner.run_game('league-0001')
    service._write_json(directory / 'status.json', {'status': result.status, 'experiment_id': eid})
    print(json.dumps({'status': result.status, 'returncode': result.returncode,
                      'budget': service.ledger.budget_state(eid)}, default=str), flush=True)
    raise SystemExit(result.returncode or 0)


if __name__ == '__main__':
    main()
