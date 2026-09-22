# Speed, token, context, and cost plan — proposal for approval

Prepared September 22, 2026. This is a proposed treatment plan. The operator
stopped the seven-model baseline after the completed Spring 1901 checkpoint.
Its measured report is
`results/efficiency-audit-20260922-d54ea8d8/EFFICIENCY_REPORT.md`.
Spring is a complete movement phase, but is not a completed game year.

## What is actually slow

The baseline has three full-press rounds in each of Spring and Fall. With seven
survivors and draws allowed, it schedules at least **98 API calls** in the first
year, before retreats, builds, and retries. Seven initialization calls happen
only once. Press stages wait for all seven models. The current OpenRouter
semaphore permits one request across Meta, DeepSeek, and Kimi, so each round
contains at least three serial provider calls. Even if the engine takes
milliseconds, the critical path is therefore provider output time plus barriers.

The audit saw Kimi K3 return a successful press response after 505 seconds
of provider service time. Its raw usage contained **13,243 reasoning tokens** and
996 visible output tokens; `finish_reason=stop` rather than a 16,000-token cap.
Another Kimi press response took **684 seconds**. Across its seven Spring calls,
Kimi used **37,901 reasoning tokens** and accounted for **$0.411 of $0.872**
Spring spend. Spring's movement phase took **2,415 seconds (40.2 minutes)**;
initialization took another **113 seconds**. All seven Spring order calls
completed successfully and the local engine adjudicated their orders.
This directly supports investigating provider-native reasoning control and
endpoint performance. It does not establish that Kimi itself is always slow:
the routed endpoint, prompt, generated tokens, and provider load all matter.
OpenRouter's own guidance distinguishes provider routing by throughput and
latency, and notes that `max_tokens` filters eligible endpoints.

The `max_tokens=16000` request cap is not a context window. For example, the
current cheapest Maverick endpoint exposes 128,000 context tokens and 16,384
output tokens, while another endpoint offers 1,048,576 context tokens and the
same output limit at a slightly higher rate. That provider-specific maximum is
more informative than the model page's aggregate 1M context number. Kimi K3
and DeepSeek V4.1 Flash have endpoints with approximately 1M context and far
larger output caps. The actual first-year prompts so far are only a few thousand
tokens, so context exhaustion is not yet measured. Some history disappears
because `prompt_constructor.py` deliberately omits it, not because the model
refused a longer prompt.

## Proposed changes in order

### 1. Make the measurements trustworthy before optimizing

Use the completed Spring's raw call records, provider IDs, output
reasons, prompt size, usage categories and phase duration as the initial baseline.
It does not establish Fall, Winter, elimination, draw, or long-horizon memory
costs; obtain those with a separately budgeted pilot after approval.
Add per-call first-token time (via streaming where supported), provider endpoint,
input and output tokens, reasoning tokens, actual response length, and queue
time to the durable trace. Separate queue time from provider service time.
The existing Gemini SDK omitted thoughts tokens from its usage object, even
though the reported total exposed them. Derive an explicitly marked estimate
from documented totals for historical calls and migrate to the maintained
`google.genai` SDK to capture native fields for future ones.

Fix the remaining correctness issues identified in the guide before comparing
strategies: validate complete order sets on isolated game snapshots; wire an
optional plan into the order context; prevent infrastructure outages from being
treated as silent press/order decisions; make phase action checkpoints resumable;
and retain the audit's exclusion of unfinished games from standings. These fixes protect the benchmark
from measuring a harness defect instead of the models.

**Gate:** a mock full year with press, retreats, Winter, draws, interruptions,
and exactly one committed action per successful provider request. Then repeat a
short paid calibration only by explicit launch and budget.

### 2. Recover parallelism on the current critical path

Make the OpenRouter per-account concurrency limit configurable and test values
1, 2, and 3 with the same roster and prompt/output settings. Keep the press
barrier: parallel calls may start together, but accepted messages become
visible only after all responses in that round arrive. Apply a global account
concurrency and rate gate across games, backed by the existing atomic monetary
reservation. Do not assume three-way concurrency works just because a single
call works; low-credit keys and endpoint limits can reject parallel requests.

Allow several independent games to run at once after phase-level durability is
in place. One 20-year game still has its own sequential phase chain, but 50
games need not run consecutively. Five concurrent games could reduce the
wall-clock contribution of independent games toward one fifth, subject to
provider capacity and common budget limits. This is a scheduling estimate,
not a measured speedup.

**Gate:** identical accepted orders and message visibility under concurrency
1 versus 3 in mock runs; paid short pilot shows no material increase in
429/402 errors, unknown charges, or cost per year.

### 3. Cut repeated tokens without deleting permitted information

Remove the random prefix in `utils.generate_random_seed` from provider calls;
the game seed and model sampling settings can remain versioned separately.
Put stable neutral rules, schemas and role information first, then changing
board/press/diary information. Avoid embedding the same system instructions
again in the order user prompt. Do not paste the same last three messages twice.
Memoize the legal-order graph per phase/power locally; it should not be rebuilt
for every press round. Replace the repeatedly reprocessed older diary archive
with an incremental private summary, while retaining raw entries for audit.

Shrink generated output where the task needs little text, using stage-specific
JSON schemas, explicit maximum response lengths, and complete-set validation.
Initialize goals in a short schema. Press should allow `[]` silence without a
forced paragraph to every power. Orders should return only legal order strings
for that phase. Diary summaries should target brief factual commitments and
uncertainties. Keep the same informational entitlement across all models and
version any prompt treatment, because it can affect strategic performance.

**Gate:** compare input/output/cache usage by task and invalid response rate on
matched mock games, then a budgeted multi-model pilot. No arbitrary global
output cap that exhausts reasoning before a visible order is emitted.

### 4. Test fewer API stages as separate treatments

The negotiation diary is currently the bridge from press to orders because the
simple order prompt omits raw messages. Deleting that call alone would hide
information. A fair alternative is one order call that includes only the
player's allowed press plus its private diary, and returns both an order set and
a brief private note. Another treatment could append phase-result facts to a
deterministic diary and defer the model's reflective update to the next call.
Likewise, initialization may be combined with the first Spring decision in a
distinct treatment. These changes can remove up to 7 to 28 sequential or
parallel requests per first year, but alter behavior and memory. Measure game
quality, legal-order rate, draw behavior and cost alongside latency.

Three, two and one negotiation round should be explicit experiment settings,
not a hidden optimization. If the research question is full press, zero rounds
is a different game mode. Native reasoning effort should be set and frozen per
model, not forced to a common numeric value that means different things to
different providers. Kimi K3's documentation says it always reasons and its
default effort is `max`; `low` is a plausible latency/cost treatment worth a
paired pilot. The observed 13,243 hidden tokens on one press response make it
high priority, but changing effort mid-game would invalidate the baseline.

**Gate:** matched seed/country rotations with one changed treatment at a time;
judge quality and stability, not just dollars or minutes.

### 5. Route each requested model to suitable infrastructure

Capture an endpoint snapshot before each run. Filter by exact model/version,
supported parameters, minimum context, minimum completion budget, privacy
requirements and a conservative maximum price. Then compare eligible endpoints
on measured latency and cost. This can choose a faster host for the **same**
model without substituting a different model. Record the resolved provider, so
mixed-host benchmark results remain explainable. A route pin increases
reproducibility but removes automatic provider failover; allow a documented
policy per experiment.

OpenRouter's current public endpoint snapshot in
`results/efficiency-audit-20260922-d54ea8d8/endpoint_catalog.json` shows:

| Model | Example endpoint | Context | Output cap | USD / 1M input, output |
| --- | --- | ---: | ---: | ---: |
| Llama 4 Maverick | DigitalOcean | 128,000 | 16,384 | 0.1875, 0.6525 |
| Llama 4 Maverick | DeepInfra | 1,048,576 | 16,384 | 0.20, 0.80 |
| DeepSeek V4.1 Flash | DeepInfra | 1,048,576 | 131,072 | 0.14, 0.42 |
| Kimi K3 | Inference.net | 1,048,576 | 943,718 | 1.50, 7.50 |

These are catalog listings, not guarantees of availability, speed, or actual
billed rates. DeepSeek has time-of-day rates and OpenRouter reports the charge
for the selected route. Retain the actual reported cost. `max_tokens=16000`
fits DigitalOcean Maverick but a larger request could silently remove that
cheap route; test the intended eligible endpoint set before launch.

Compare direct DeepSeek (`deepseek-flash`) and direct Kimi API where account
access is available. Direct DeepSeek lists $0.15/$0.60 off-peak and
$0.30/$1.20 at peak, with $0.003/$0.006 cached input; the cheapest listed
OpenRouter endpoints can undercut direct rates. Direct access may improve
control or latency even if its sticker rate is higher. xAI remains native xAI,
as required. Do not route Grok through OpenRouter as a cost shortcut.

For this exact roster, current standard advertised rates per million tokens
(input/output, excluding cache effects) are:

| Competitor | Tested route or candidate | USD / 1M input, output | Main cost issue |
| --- | --- | ---: | --- |
| OpenAI Terra | OpenAI direct, standard | 2.00, 12.00 | Many calls and output/reasoning |
| Anthropic Opus 4.7 | Anthropic direct | 5.00, 25.00 | Highest list output price |
| Gemini 3.8 Flash | Google direct, promotion through 2026 | 0.75, 3.75 | Thinking counted as output |
| Llama 4 Maverick | OpenRouter DigitalOcean | 0.1875, 0.6525 | 128k endpoint context |
| DeepSeek V4.1 Flash | OpenRouter DeepInfra listing | 0.14, 0.42 | Route/availability varies |
| Grok 4.20 | Native xAI global | 1.25, 2.50 | Reasoning billed as output |
| Kimi K3 | OpenRouter Inference.net listing | 1.50, 7.50 | Very large reasoning output observed |

The lowest per-token listing does not necessarily produce the cheapest full
game: output and hidden reasoning volumes vary greatly. Use final measured
costs by task, then compare alternative routes for the same exact model.

### 6. Compare real whole-run economics, including subscriptions

For each proposed treatment, report **actual USD, input/visible/reasoning/cache
tokens, wall time, invalid order rate, provider error rate, and country-balanced
game results**. Apply today's price snapshots to historical token patterns,
but retain historical charges at their original price. Cost forecasts should
cover the selected route, phase types, expected active powers, memory growth and
retry frequency. The first year is a cold start, not a credible 20-year
estimate; calibrate with several complete games before reporting tight ranges.

OpenAI standard short-context prices are twice the Batch/Flex entries that had
been mislabeled in `config/labs.yaml`; the catalog has been corrected. Batch
and Flex are worth considering for independent, non-urgent work, but a live
Diplomacy phase must wait for every power. A slow discount tier can raise
time-to-completion substantially. Gemini's current promotional rate ends
December 31, 2026; forecasts must track that effective date.

OpenRouter says it passes through provider inference prices without a markup,
but charges a platform fee on credit purchases. Its Standard pricing page
currently lists 5.5%; account and payment terms may vary. Do not call a paid
consumer chat subscription a source of general inference credits. OpenAI's
ChatGPT plan and API pricing are separate. Anthropic's current subscription
guidance has a paused change notice; claimed Agent SDK monthly credits in the
older part of that page are **not active**. Some Agent SDK usage may count
against subscription limits, but the current `AsyncAnthropic` API-key harness
remains metered. Treat any alternative subscription route as a distinct,
terms-checked integration rather than swapping a key in the current client.

## Approval scope

I propose implementing stages 1–3 first, then running paired, budgeted trials
for stage 4 and endpoint/route trials for stage 5. Each change gets a versioned
configuration switch so the original baseline can be reproduced. Do not run
new paid comparison trials until the operator sees the call-count and full-run
forecast and supplies a budget.

## Sources checked September 22, 2026

- [OpenAI pricing](https://developers.openai.com/api/docs/pricing),
  [latency optimization](https://developers.openai.com/api/docs/guides/latency-optimization),
  [prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing),
  [current Agent SDK plan notice](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
- [Google Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing),
  [usage metadata definition](https://ai.google.dev/api/generate-content)
- [OpenRouter routing](https://openrouter.ai/docs/guides/routing/provider-selection),
  [reasoning token behavior](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens),
  [platform pricing](https://openrouter.ai/pricing)
- [DeepSeek direct pricing](https://api-docs.deepseek.com/quick_start/pricing/),
  [Kimi K3 reasoning settings](https://platform.kimi.ai/docs/guide/kimi-k3-quickstart),
  [xAI token billing](https://docs.x.ai/developers/pricing)
