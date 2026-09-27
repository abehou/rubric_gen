# HealthBench Dev3 v6 — candidate tasks, neutral revision and task-grounded RTT

2026-09-26 18:08 PDT. User selected and authorized the three new candidates;
implementation and offline checks complete, launch receipt tracked in EXPERIMENT_RUNS.md.

## Scope

The user's final selection supersedes the temporary old-Dev3 choice. Config
[dev3-v6.yaml](dev3-v6.yaml) uses `rh-dev3-20260926-v6`:

| Task | Official source ID |
| --- | --- |
| dev-001: weight discrepancy and patient attribution | 47a50742-10ba-462a-84bb-a119bfe360af |
| dev-002: wound example versus current record | d716ca0e-52b9-491b-92b4-1d74e450314c |
| dev-003: sparse inpatient dictation versus complete SOAP note | 5f539a2c-85f4-4cc9-8790-e1b23d950954 |

All three are disjoint from prior prepared Dev3/Result20 pools, with8 original
criteria each. Selection is based on task/rubric content, not solver outcomes or
RTT wins. They are not previously validated RH-positive tasks. Original prompts,
signed points and source records are intact. No old task or result was overwritten.

Three replicates × four Full/User × static/RTT conditions =36 assignments,
three revisions, five rubric variants (selected0/development1/heldout2–4).
Relative to the prepared v5 YAML only dataset/output directories change. The previously
executed v4 had validation-low; v6 retains the already-approved v5 validation-high
allocation, also used in Result20. Hence v4→v6 is not a single-factor ablation.

- Solver, seed and W: gpt-5.6-luna low.
- RTT generator, diagnostics, induction and validation: gpt-5.6-luna high.
- Paraphrase/user simulator: existing5.6-Luna allocation, unchanged.
- S/H/A/pairwise and four RH windows: gpt-6-luna high, no Sol/Anthropic calls.
  This is the cheap development panel, not Result20's Sol A/pairwise panel;
  do not interpret A changes across those panels as a treatment effect.

## Changes

1. HealthBench's shared revision instruction retains `Preserve correct content.`
   but removes the additional anti-fabrication sentence for **all** conditions.
   Original task/rubric requirements, research-tool restrictions and simulator
   factuality constraints remain. ResearchQA's contract is unchanged.
2. HealthBench's existing sidecar generator now targets a task-grounded answer
   defect that the rubric could reward or overlook; computation is relevant only
   if the task requires it. It separates synthetic defects from natural behavior
   and asks for observable evidence. BioMNIBench/ResearchQA attack prompts and
   versioned trace-defense recipes are unchanged. No proposer architecture changed.
3. Uses the previously implemented RH task/window guidance; no threshold change.
   W/S/H/A and gap definitions stay fixed. New and old RH labels remain separate.

## Verification

43 focused offline checks pass for final candidate config, source preservation,
sidecar dispatch/reuse, private launcher/credential isolation and existing budget
relay. The earlier42 detection checks also passed. `git diff --check` passes on
edited tracked code/tests. No paid smoke or screening calls.

## Pre-run forecast and approved execution budget

Update2026-09-26 18:41 PDT: the user explicitly authorizes finishing this same
Dev3 beyond$3. The original owner stopped at$1.77891163 recorded spend with
zero unknown/pending usage because a$1.2304 worst-case request reservation
exceeded remaining headroom, not because the invoice had reached$3. Retain the
original ledger limit for provenance but enable allow_overrun on missing-only
revision/audit recovery; no model/task changes. Updated provisional total
estimate$2.5–4.5 and20–40minutes remaining will be compared with final actuals.
The original forecast below is preserved as historical evidence.

Old v4 full-trajectory detected counts: Full-static2/9, Full-RTT1/9, both User
conditions0/9; all final-artifact counts0/9. The three positive judgments concern
dev-003's rubric-requested conditional referral absent from the original
dictation. They are not three independent mechanisms or established gold labels:
check whether the answer falsely records a plan or clearly offers new advice.

These old rates are background only, not observations of the new candidates.
The new-task low-confidence planning forecast is1–3 detected full-trajectory RH
cases among18 baseline assignments (roughly6–17%); zero is also plausible.
This is a subjective scenario, not a calibrated interval or a quota. Report
Full/User separately after the run. A reduction with RTT is the hypothesis,
not an already-supported prediction. Final-artifact RH may remain zero.

Saved v4 usage, via existing `usage_snapshot.snapshot` per stage, totals about
7.41M input and0.555M output tokens (reasoning included). Repricing the pre-audit
stages as5.6-Luna and audit as6-Luna yields approximately$1.21; saved usage is not
an invoice and missing failed-call usage is excluded. The estimator deduplicates
within stage, not across stages, so this is a planning anchor rather than a ledger.
Allowing for high validation, different task context, longer RH guidance,
new sidecar behavior and retries:
**estimate$1.5–3 for the complete36-assignment Dev3**, not a guaranteed upper bound.
Rates checked against [official Standard pricing](https://developers.openai.com/api/docs/pricing)
on2026-09-26. The user's instruction to run these candidates authorizes this Dev3;
the existing budget relay imposes a separate$3 hard cap with no overrun. If actual
cost/reservations prevent completion within it, preserve work and report before
any budget extension; completion below$3 is an estimate, not a guarantee.

Mac profile: outer shared queue1, assignment6, aggregate provider12, internal
fanout4, audit12; host12CPU/24GiB with no resource reservation. Plan30–60minutes
from prior same-size Dev3, allowing additional high-effort work; check competing
jobs before dispatch. New root: `runs/healthbench-hard-rh-dev3-20260926-v6/`.
The existing native seed/paraphrase/revise/detect workflow and Result20 budget
relay are reused by the private [run_dev3_v6.py](run_dev3_v6.py) launcher; it
archives source including untracked prompt files and holds a single-owner lock.
At18:08 no competing experiment owner or relay listener was found; free memory48%.

Report endpoints W/S/H/A and gaps, per-round observed W, four RH windows and
task-level evidence for changed detections/RTT repairs. Do not claim per-round
independent S/H/A measurements where none are collected. This is new-task
development, not a paired estimate of improvement over old Dev3. No Result20
promotion is authorized.
