# HealthBench Hard challenge Result20 — approved 2026-09-25

Completed September26: all240solver assignments and3102unique audit judgments.
Final conservative ledger$27.536529205. See [RESULTS.md](RESULTS.md) for the
complete outcome/trajectory analysis and [TABLES.md](TABLES.md) for all20task
comparisons; `analyze_result20.py` regenerates the saved-artifact numeric analysis
without provider calls. The older forecasts below are historical launch context.

September26 interpretation correction and saved-request RH/S−H investigation:
[RH_MEASUREMENT.md](RH_MEASUREMENT.md). High revision scores are an achieved
objective; sparse detector positives must not be equated with eliminating RH.

RH-only task/window guidance is now implemented and checked offline:
[RH_REAUDIT_PREP.md](RH_REAUDIT_PREP.md). Prepared6Luna-high four-window re-audit
estimate$2.08, proposed cap$3; no paid launch yet and no solver/quality-audit rerun.

September26 audit recovery: the user explicitly authorizes completing this audit
even if the original$30 total is exceeded. `resume_audit.py` runs only native
`detect --resume`, preserving solver outputs and the failed audit record; it keeps
cost accounting but opts out of the monetary stop for this invocation only.
The original full-workflow launcher remains capped. Expected additional$9–11,
Mac audit12/provider12, one shared queue, no solver workers, estimated60–90min.
This update supersedes the original budget ceiling below only for this audit.

20 content-reviewed English-language questions, three replicates, four conditions
(Full/User simulator × static/RTT), exactly three revision turns. This is a
purposefully selected challenge subset, not an unbiased HealthBench Hard score.
`selection.json` records source IDs, content-based selection rationale and explicit
contradiction exclusions; no solver outcome or RTT win was used to select tasks.
No claim of clinician validation or guaranteed post-feedback difficulty is made.
All source prompts, criteria and signed points remain unchanged. The existing
explicit predicate/penalty adapter renders fresh task files.

The pool has 10–17 criteria/task (mean13.5), mean1792 prompt characters and4579
rubric characters. Dev3 means were8.67,359 and2779 respectively. It is disjoint
from every saved HealthBench Dev3 source ID. Historical Result20 remains intact.

Solver/W=5.6Luna low; RTT/red-team=5.6Luna high, including validation.
S/H and all four RH windows=6Luna high. A and native initial-versus-final pairwise
preference=6Sol high, not an extra duplicate Luna panel. H has three heldouts.
Pairwise is **not** a new direct RTT-versus-static judge; compare those arms using
matched endpoints and inspect their actual answers across all20tasks.

Use the same native seed→paraphrase→revise→detect commands via `run.py` and
`local.yaml`. On September26 the user explicitly selected Mac execution after
disclosure of approximately five hours, superseding the unlaunched Babel plan.
One shared240-assignment queue has6 assignment workers, provider aggregate12,
fanout4, and12 audit workers. This does not serialize independent task shards:
all20tasks share the same work queue and pretreatment across conditions.
Host12CPU/24GiB, no resource reservation; expected4–6h from44min Dev3 throughput.
Output root: `runs/healthbench-hard-challenge20-local-20260926/`.
Reuse the existing local `.env.local` credential; no remote credential copy.
The old shard YAMLs and Slurm launcher are unlaunched preparation artifacts and
are not the approved execution entrypoint.

Budget: $30 total authorized. Original token-matched mixed-panel estimate$10.61;
plan$16–22 for longer questions/rubrics and high validation, not a guaranteed
completion cost. Private loopback relay owns the only valid provider key. Worker
processes receive a random dummy credential. All solver and hosted Requests use
the relay, which reserves conservative input/output upper bounds before each
billable call and settles observed usage; unknown failed-call usage stays charged
at the bound. In-flight reservations count toward the limit; a request that cannot
be funded is refused, preserving partial experiment outputs. No hosted tools,
background calls, hidden server-side conversation state, or unapproved models are
allowed. Prices use Standard short/long-context cache-aware token rates, not tax
or an account invoice. Content is forwarded only to official api.openai.com.

No separate paid smoke or screening run. Offline checks cover native mixed-model
routing, task/config cardinality, original scoring, and budget admission/recovery.
The actual dirty source, source diff and invocation receipt are preserved. Freeze
runtime source once launched; use native `--resume` only after terminal failures.
Report complete coverage before interpreting results; task-level n=20, not240.
# Current checkpoint — 2026-09-27

The complete eight-condition matrix is in [MATRIX.md](MATRIX.md); the 480
individual endpoint/gap/RH records are in
[matrix-case-metrics.jsonl](matrix-case-metrics.jsonl). Full/User RH uses the
completed answer-only-v2 re-audit, not the earlier sparse detector output in
historical reports. Semi/Score-only completed all 240 revisions and 3,097 unique
audit judgments. Their ledger records $28.342326735, including four conservative
unknown-usage reservations, with no pending usage.

Raw trajectories, datasets, seed/paraphrase pools, and invocation/source archives
remain local under the run paths in MATRIX.md; they are not included in this Git
checkpoint. In particular, `prepare_remaining.py` preserves the original
Result20 prompts using the local `output/healthbench-result20-preparation/source.tar.gz`
archive. The current v6 prompts are a later development variant, not the source
used to generate this matrix. Replaying historical analysis scripts also requires
the local raw outputs and their generated JSON analysis files. Do not interpret
this checkpoint as a portable raw-run archive or rerun any experiment to read the
published compact matrix.
