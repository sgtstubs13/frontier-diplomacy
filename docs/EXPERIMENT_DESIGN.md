# Frontier Diplomacy League experiment design

The league treats the lab as the persistent competitive identity and records the exact provider/model configuration used for every game. Players receive a power and standardized game information; lab identities are stored externally for analysis and are not exposed to other agents by default.

## Scheduling

`frontier-diplomacy schedule` creates the full season schedule before execution. It uses a seed and soft balance penalties for lab appearances, lab/power assignments, and pairwise encounters. The generated JSON is the authoritative assignment artifact.

Partial seasons cannot always make every matrix cell equal. The schedule should therefore be validated and its balance reported before any paid run.

## Rollout

1. Generate 2–3 smoke games with cheap/local models.
2. Run a 7–14 game pilot with the intended provider mix.
3. Freeze labs, exact model IDs, prompts, tournament settings, and the code commit before a 50–100 game season.

The environment and schedule are reproducible from configuration, seed, and commit. Provider generations may not be bit-for-bit deterministic.
