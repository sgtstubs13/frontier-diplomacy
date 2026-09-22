"""Fetch public catalog metadata only; no credentials or model inference."""
from datetime import datetime, timezone
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
MODELS = ('meta-llama/llama-4-maverick', 'deepseek/deepseek-v4.1-flash', 'moonshotai/kimi-k3')


def main():
    snapshot = {'retrieved_at': datetime.now(timezone.utc).isoformat(), 'models': {}}
    for model in MODELS:
        url = 'https://openrouter.ai/api/v1/models/' + model + '/endpoints'
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        snapshot['models'][model] = {'source': url, 'data': response.json()['data']}
    path = ROOT / 'results/efficiency-audit-20260922-d54ea8d8/endpoint_catalog.json'
    path.write_text(json.dumps(snapshot, indent=2) + '\n')
    for model, data in snapshot['models'].items():
        endpoints = data['data']['endpoints']
        print(model, 'endpoints:', len(endpoints))
        for item in sorted(endpoints, key=lambda e:float(e['pricing']['completion']))[:3]:
            print(item['tag'], 'input/output per M:', float(item['pricing']['prompt'])*1e6,
                  float(item['pricing']['completion'])*1e6,
                  'context/output:', item['context_length'], item.get('max_completion_tokens'))
    print(path)


if __name__ == '__main__':
    main()
