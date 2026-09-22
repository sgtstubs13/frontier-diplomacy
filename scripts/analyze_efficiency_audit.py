"""Offline audit report; reads existing calls, never launches a model request."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
import sqlite3
import sys
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from frontier_diplomacy.telemetry import google_reasoning_tokens
EXPERIMENT = 'efficiency-audit-20260922-d54ea8d8'


def charged(row):
    value = row['reported_cost_usd']
    if value is None:
        value = row['calculated_cost_usd']
    return Decimal(value) if value is not None else None


def aggregate(rows):
    calls = [r for r in rows if r['task'] != 'accounting_adjustment']
    service, queue, prompt_bytes, finish, routes = [], [], [], Counter(), Counter()
    tokens = Counter()
    missing = 0
    for row in calls:
        raw = json.loads(row['raw_usage'] or '{}')
        measure = raw.get('_measurement', {})
        if measure.get('request_ms') is not None:
            service.append(measure['request_ms'] / 1000)
        if measure.get('queue_ms') is not None:
            queue.append(measure['queue_ms'] / 1000)
        prompt_bytes.append(measure.get('prompt_bytes', 0))
        response = measure.get('response') or {}
        finish[str(response.get('finish_reason', 'unknown'))] += 1
        if response.get('provider'):
            routes[response['provider']] += 1
        for key in ('input_tokens', 'output_tokens', 'reasoning_tokens', 'cached_input_tokens', 'cache_write_tokens'):
            # Audit process started before the xAI normalization fix. Normalize
            # this report from raw provider metadata, without rewriting history.
            value = raw.get('completion_tokens', row[key]) if key == 'output_tokens' and row['provider'] == 'xai' else row[key]
            if key == 'reasoning_tokens' and row['provider'] == 'google':
                value = google_reasoning_tokens(raw)
            tokens[key] += value
        missing += row['certainty'] == 'unknown'
    costs = [charged(r) for r in rows]
    return dict(calls=len(calls), costs_usd=str(sum((c for c in costs if c is not None), Decimal(0))),
                unknown_usage_calls=missing, service_seconds_sum=round(sum(service), 3),
                service_seconds_median=round(median(service), 3) if service else None,
                service_seconds_max=max(service, default=None), queue_seconds_sum=round(sum(queue), 3),
                prompt_bytes_max=max(prompt_bytes, default=0), tokens=dict(tokens),
                finish_reasons=dict(finish), routes=dict(routes), outcomes=dict(Counter(r['outcome'] for r in calls)))


def analyze(experiment=EXPERIMENT):
    folder = ROOT / 'results' / experiment
    game_dir = folder / 'games' / 'league-0001'
    with sqlite3.connect(f'file:{ROOT / "data/frontier_diplomacy_costs.sqlite"}?mode=ro', uri=True) as con:
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute('SELECT * FROM usage_records WHERE experiment_id=?', (experiment,))]
        reservations = [dict(r) for r in con.execute('SELECT state, amount_usd FROM reservations WHERE experiment_id=? AND state != ?', (experiment, 'reconciled'))]
    spring_rows = [row for row in rows if row['phase'] == 'S1901M']
    fall_rows = [row for row in rows if row['phase'] == 'F1901M']
    grouped, tasks = defaultdict(list), defaultdict(list)
    for row in spring_rows:
        grouped[row['model_id']].append(row)
        tasks[row['task']].append(row)
    text = (game_dir / 'general_game.log').read_text()
    phases = re.findall(r'Phase (\w+) took ([\d.]+)s', text)
    response_rows = list(csv.DictReader((game_dir / 'llm_responses.csv').open(newline='')))
    status_path = game_dir / 'status.json'
    status = json.loads(status_path.read_text()) if status_path.exists() else {'status': 'no_terminal_status_yet'}
    game_path = game_dir / 'lmvsgame.json'
    saved = json.loads(game_path.read_text()) if game_path.exists() else None
    saved_phases = saved.get('phases', []) if saved else []
    # Event timestamps identify still-in-flight calls independently of status.json.
    events = [json.loads(line) for line in (game_dir / 'calls.jsonl').read_text().splitlines()]
    done = {e['request_id'] for e in events if e['event'] == 'finished'}
    pending = [e for e in events if e['event'] == 'dispatched' and e['request_id'] not in done]
    report = dict(experiment=experiment, generated_at=datetime.now(timezone.utc).isoformat(),
        terminal_status=status, total_ledger=aggregate(rows), spring=aggregate(spring_rows),
        fall_partial=aggregate(fall_rows), by_model={m:aggregate(r) for m,r in grouped.items()},
        by_task={m:aggregate(r) for m,r in tasks.items()}, completed_phase_seconds=dict(phases),
        completed_saved_phases=[p['name'] for p in saved_phases if p.get('results')],
        saved_current_phase=saved_phases[-1]['name'] if saved_phases else None,
        in_flight=pending,
        reservation_states=dict(Counter(r['state'] for r in reservations)),
        response_statuses=dict(Counter(r['response_type'] + ': ' + r['success'] for r in response_rows)),
        limitations=['Only Spring 1901 was completed; no full-year, long-game quality or forecast calibration conclusion.',
                      'Service time includes provider queue/prefill/decode; no streaming TTFT measurement.',
                      'Queue sums overlap other requests: never add them to wall-clock time.',
                      'Costs include explicit accounting adjustments; unknown charges are not zero.',
                      'xAI visible-output totals in this report are normalized from raw usage.',
                      'The worker loaded code at experiment start; later source fixes and tests apply only to subsequent workers. See code.patch for the launch snapshot.'])
    report['limitations'].append('Gemini reasoning is derived from provider total minus prompt minus candidates when the old SDK omits thoughts_token_count.')
    (folder / 'efficiency_metrics.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = ['# Spring 1901 efficiency audit — measured results', '',
             f'Experiment: `{experiment}`. Report generated {report["generated_at"]}.', '',
             f'Worker status: **{status["status"]}**. Completed saved phases: {", ".join(report["completed_saved_phases"]) or "none yet"}.', '',
             f'Spring accounted cost including audited adjustments: **${report["spring"]["costs_usd"]}**. '
             f'Spring finished attempts: {report["spring"]["calls"]}. '
             f'Unknown-usage attempts: {report["spring"]["unknown_usage_calls"]}.', '',
             f'Partial Fall charges from requests dispatched before cancellation: **${report["fall_partial"]["costs_usd"]}** '
             f'for {report["fall_partial"]["calls"]} completed attempts. '
             f'Total accounted spend: **${report["total_ledger"]["costs_usd"]}**. '
             f'{len(pending)} interrupted request(s) retain unresolved budget exposure.', '',
             '| Model | Calls | Service median (s) | Service max (s) | Queue sum (s) | Input | Visible output | Reasoning | USD |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for m, r in report['by_model'].items():
        t = r['tokens']
        lines.append(f'| {m} | {r["calls"]} | {r["service_seconds_median"]} | {r["service_seconds_max"]} | {r["queue_seconds_sum"]} | {t.get("input_tokens",0)} | {t.get("output_tokens",0)} | {t.get("reasoning_tokens",0)} | {r["costs_usd"]} |')
    lines.extend(['', '## Measured completed phase times', ''])
    lines.extend(f'- {phase}: {seconds} seconds' for phase, seconds in phases)
    lines.extend(['', '## Interpretation limits', ''])
    lines.extend('- '+item for item in report['limitations'])
    (folder / 'EFFICIENCY_REPORT.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({k:report[k] for k in ('terminal_status','spring','fall_partial','total_ledger','completed_phase_seconds','completed_saved_phases','reservation_states')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment', default=EXPERIMENT)
    analyze(parser.parse_args().experiment)
