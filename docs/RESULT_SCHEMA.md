# Result schema (planned)

The league runner will preserve immutable per-game artifacts under `results/<season>/games/<game-id>/`:

- `metadata.json`: lab, exact model/provider, power, seeds, timestamps, commit, prompt and engine versions, parameters.
- `final_state.json`: final engine state and supply-center ownership.
- `orders.jsonl`: submitted, accepted, rejected, and repaired orders by phase.
- `messages.jsonl`: private/global negotiation messages.
- `model_calls.jsonl`: request metadata, token usage, latency, retries, and categorized failures.
- `summary.json`: termination reason, final supply centers, survival/elimination, and aggregate metrics.

Raw source messages remain traceable for any heuristic negotiation classification. Provider failures are recorded separately from strategic outcomes and never count as a Diplomacy loss.
