# Result20 runtime reliability implementation

Implemented in a new isolated worktree at
`/home/aydanh/repos/rubric_gen/runs/babel-code/runtime-reliability-review`, branch
`review/result20-runtime-reliability`, initially based on reviewed scientific
commit `4c6f321846147b50d8cf47f6b2dc05f515e14063`. Newer remote commits are retained
when rebasing this patch for the requested non-force push to `origin/aydan-red-team`.
The main checkout's dirty files, active job sources, live state and scientific
output namespaces were not changed. No scientific experiment or provider call
was launched. Slurm jobs 10397916 and 10397928 only read existing NFS evidence.

## Evidence and scope

The [failure census](result20-failure-census.md) precedes implementation. Native
PaperBench audits rejected 229 count-invalid attempts across the original and
unchanged recovery jobs. Seven v1–v4 schema attempts were rejected for provider
complexity. The accepted v5 validation (10392624) passed 145/145 and 872/872 on
first calls. The subsequent v5 recovery had 18 API timeouts on six terminally
missing judgments: about 90 aggregate request-minutes, within an 88m24s job that
also did successful work. Streaming recovery 10394282 completed all six; actual
stream durations were 318–1,223 seconds.

BioMNIBench evidence also shows Codex startup/session failures, a historical
Slurm preemption, and five terminal Anthropic 529 judgments recovered with native
`detect --resume`. It does not establish a need to reduce the 7,200-second solver
turn limit or change Gemini transport. Those paths are outside this repair.

## Changes and why the old mechanisms were insufficient

| Owner | Change |
|---|---|
| `src/rubric_gen/runtime/provider_streams.py` | Shared single-request Anthropic Messages SSE and OpenAI Responses SSE consumption; require terminal completion; close clients/streams on all exits. Translate mid-stream HTTPX timeout/connection errors to the same SDK error classes used before streaming, keeping existing error classification and retry behavior. |
| `src/rubric_gen/submission_revision/judging/full_rubric_judge.py` | Route Anthropic/OpenAI full-rubric revision judgments through the shared streaming transport with unchanged request bodies and budgets. |
| `src/rubric_gen/submission_revision/evaluation/rubric_judge.py` | Use the same transport for independent rubric audits; select tested indexed encoding for Anthropic, measure its actual schema/prompt size, decode through the existing canonical validator/scorer, and record the actual representation in existing execution/usage metadata. Preserve earlier failed attempts on resume. |
| `src/rubric_gen/submission_revision/evaluation/indexed_rubric.py` | Factor the accepted v5 format paragraph, shared tree schema and strict decoder from the locally validated recovery script. No recovery-script dependencies or benchmark-specific logic. |
| `src/rubric_gen/submission_revision/judging/full_rubric_protocol.py` | Existing execution/usage records now disclose streaming and network-inactivity timeout semantics for Anthropic/OpenAI. The 300-second value, retry count, model settings and scoring remain unchanged. |
| `src/rubric_gen/submission_revision/judging/executor.py` | Raise the full-rubric child-process absolute ceiling from 360 to 3,600 seconds; include the factored transport source in existing provenance coverage. |

Existing provenance source lists also include the factored indexed-format module.
No new hash scheme, baseline, frozen contract, CLI command, preflight mode, gate,
heartbeat system, dependency, or recovery framework was introduced. Existing
validation, atomic publication, bounds and provenance checks remain in force.

## Timeout semantics

| Boundary | Before | After |
|---|---|---|
| Anthropic/OpenAI HTTP transport | Non-streaming request with a 300s timeout: an otherwise healthy long response can produce no response body before the timeout | Streaming, with 300s network read inactivity. Total elapsed response time may exceed 300s as bytes arrive, including keepalives. |
| Full-rubric judge subprocess | Absolute 360s ceiling | Absolute 3,600s ceiling to bound genuinely wedged children; no heartbeat machinery. |
| Provider retries | Zero SDK retries; existing bounded outer attempts | Unchanged. One provider request per judgment attempt. |
| Solver/Codex turn | Up to 7,200s | Unchanged. |

The independent audit scorer runs in-process; the subprocess ceiling belongs to
the revision/full-rubric judge. Both use the same new transport. Gemini's provider
schema, HTTP timeout, request parameters and retry policy are unchanged; the
shared full-rubric subprocess safety ceiling applies to that child path too.
HTTP connect/write/pool waits retain the same SDK 300s timeout setting. An initial
response with no activity for 300s still fails. Partial/truncated streams never
become valid judgments. A response exceeding one hour can still hit the absolute
child ceiling; the observed successful maximum was approximately 20m23s.

## V5 representation and scoring

Anthropic rubric audits use v5 at every rubric size. The limitation is
provider-specific; a size threshold would leave unsupported exact array counts
at smaller sizes (the 145-criterion failure was observed). OpenAI and Gemini keep
their existing array representation. The revision judge's scientific schema and
prompt are unchanged; only its transport changes.

A single full-rubric request returns `floor(N/64)` explicitly indexed blocks of
64 leaves plus a fixed-size tail. Each leaf is `level_index|reason`. For 872
criteria this is 13 blocks and 40 tail leaves. Left-before-right traversal and
the unchanged `criterion_contracts` order identify every original criterion ID.
Blocks may arrive in any array order; explicit indices restore canonical order.
Duplicate/missing/extra indices, malformed trees, duplicate JSON keys, invalid
indices and empty reasons fail validation. No record is padded, dropped, or
reassigned based on text matching.

The decoder produces the same ordered level-index records consumed by the
existing canonical validator. Signed points, per-criterion level mapping,
normalization and final aggregation are unchanged. The complete rubric and
artifact remain in one provider request with the same model, effort and output
limit; these are not independent judgments of rubric chunks.

A provider-free comparison against the actual local
`scripts/babel/paperbench_keyed_protocol.py` proved exact schema equality for
1/64/145/872/1000 criteria and exact full format-prompt equality. This is a tested
representation change, not evidence that stochastic model outputs are identical
across encodings. The census retains four v5 validation failures subsequently
recovered by existing bounded retries.

## Resume behavior

Existing `RubricScoreStage._run_job` validates and returns each saved valid
judgment before provider dispatch. `RubricScoreJudge.evaluate` also reuses a
valid published judgment if interruption occurred before its stage record was
written. Missing judgments alone reach evaluation, under the existing three
attempts per invocation. Corrupt or incompatible stored stage records still fail
clearly; this patch does not silently reinterpret historical artifacts.

The concrete missing piece was `failed-attempt-001.json` numbering restarting
on each invocation. Ordinary resume could overwrite earlier failure evidence,
forcing the historical manual archive. Publication now finds the next unused
number under the existing evaluation lock and retains atomic JSON writes.
Successful judgments are untouched and the attempt budget is unchanged. The
former v5 supplemental scripts were needed because the frozen producer did not
have the working provider representation/transport; future current-code runs
use those directly through ordinary resume.

Historical results keep their original identities. Changed source/transport
metadata can make historical outputs incompatible with current validation;
this patch does not migrate, relabel or resume any active/historical experiment.

## Verification

The installed locked environment was reused without installation: Python 3.12,
Anthropic 0.120.0, OpenAI 2.48.0, HTTPX 0.28.1. `PYTHONPATH=src` selects the isolated
worktree; test capacity state is isolated by the existing `tests/conftest.py`.

Focused/regression command (173 tests passed):

```bash
PYTHONPATH=src /home/aydanh/repos/rubric_gen/.venv/bin/python -m pytest -q \
  tests/test_runtime_reliability.py tests/test_evaluation_rubric_judge.py \
  tests/test_full_rubric_judge.py tests/test_judging_preflight.py \
  tests/test_submission_revision_judge.py tests/test_original_rubric_judge.py \
  tests/test_revision_evaluation.py tests/test_judgment_reuse.py \
  tests/test_evaluation_runner.py tests/test_paperbench.py tests/test_architecture.py
```

The new tests exercise real installed SDK parsers over fake HTTP streams, check
exact request settings/usage, timeout/connection classification, incomplete and
failed completion, and the actual executor's timeout argument/exit behavior.
Indexed tests cover 1/2/63/64/65/128/145/872/1000 criteria, sparse IDs, signed
scores, canonical order and malformed-response rejection. Existing regressions
cover full-rubric validation, PaperBench weighted scoring, BioMNIBench grading,
resume identity/record validation and provenance/usage replay.

After the suite, the no-provider demonstration runs:

```bash
PYTHONPATH=src /home/aydanh/repos/rubric_gen/.venv/bin/python -m pytest -q -s \
  tests/test_runtime_reliability.py \
  -k 'eight_minute or inactivity_timeout or (indexed_round_trip and 872) or resume_3333'
```

Results: four simulated 480s streams (both providers, both judge paths) succeed
with 120s activity intervals; 300/301s gaps time out at the fake 300s boundary for
both providers; 872 criteria round-trip with identical signed/normalized scores;
and the production resume branch dispatches exactly 27 of 3,360 fixture jobs,
preserving the 3,333 completed records and associated files byte-for-byte and
without timestamp changes. A second resume adds zero calls. All waits are fake;
there is no real-time sleep or hosted call. The fixture uses synthetic judgments
with the production record validator; separate tests cover native publication
and repeated failure/resume behavior.

Other changed files: `tests/test_runtime_reliability.py`,
`tests/test_evaluation_rubric_judge.py`, `tests/test_full_rubric_judge.py`,
this report, its sibling census, `CODE_REVIEW.md`, and `EXPERIMENT_LOG.md`.

## Scientific compatibility and remaining bottlenecks

This patch does not change solver prompts, paraphrase prompts,
selected/development/heldout roles, revision feedback contents, rubric criteria,
holistic evaluation, RH definitions, model choices, reasoning effort, maximum
output tokens, scoring normalization or auditor aggregation. Only Anthropic's
rubric-audit output-format paragraph/schema, transport/timeout semantics and
failed-attempt preservation change. OpenAI `store=False`, provider cache defaults,
benchmark inputs, persistent storage policy and existing retry budgets remain.

NFS cleanup/session startup failures, Slurm preemption, provider 429/5xx capacity,
auditor-lease waits, repeated planning/scanning and occasional malformed model
outputs remain. The evidence does not justify speculative new safeguards or a
solver-timeout redesign. Long successful calls still take their natural time;
the repair avoids throwing that work away solely at the old wall-clock boundary.
