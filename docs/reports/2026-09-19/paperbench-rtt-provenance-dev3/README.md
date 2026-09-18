# PaperBench promoted RTT Dev3

## Current decision

The corrected static PaperBench Results20 baseline is reusable and should not be
rerun. A fresh provider-free validator completed as Babel job `10491080` and
verified all 120 revisions plus all 3,360 planned Sol+Opus semantic judgments.
The earlier check `10490954` failed only because its old validator required
whole-object `grading_identity` equality across a producer-code version change;
the current validator accepts scoring-semantic equivalence while still checking
the exact rubric, submission, prompt inputs, saved evaluation, validation, and
score bindings.

The Mac PaperBench RTT Dev3 revision study is complete: 18/18 assignments, one
attempt each, from clean execution pin
`d68ec3e8729c564ef78de99829fd7931e005de94`. Every assignment manifest records
`attack_defense_v2.1_execution_verified_proactive_provenance` with the native
`red_team_trace` policy. Full and User each contribute nine assignments over
the three canonical tasks and three replicates.

The intended Sol+Opus audit is not yet complete. Opus is complete and supports
a strict single-auditor interim extraction. The configured OpenAI organization
ran out of API credits during Sol evaluation, leaving only a partial Sol panel.
No partial-panel mean is reported and RTT Results20 remains held until the Sol
gap is completed and the native two-auditor coverage gate passes.

## Baseline integrity recheck

The final static Results20 artifacts remain the source reported in
[`selected-neutral-heldout-rigorous-results20-final.md`](../../2026-09-12/paperbench-static/selected-neutral-heldout-rigorous-results20-final.md).
The current-code recheck produced:

| Stage | Verified coverage |
| --- | ---: |
| Revisions | 120/120 |
| Rubric score | 1,800/1,800 |
| Absolute score | 360/360 |
| Pairwise preference | 240/240 |
| Direct full trajectory | 240/240 |
| Direct post update | 240/240 |
| Direct final artifact | 240/240 |
| Direct final revision | 240/240 |
| Total semantic judgments | 3,360/3,360 |

All stages contain 120 Sol and 120 Opus direct assignment judgments where
applicable, no missing model, and no imputation. The historical run did have
real operational failures: one revision producer was OOM-killed, and an early
Opus audit exhausted strict formatting attempts. Native missing-only recovery
completed the one remaining revision and losslessly published the final three
complete saved Opus responses. The terminal artifacts now pass the current
read-only validator, so those historical retries are preserved provenance, not
evidence of a corrupted final result.

No new hash contract or release gate was added. Existing SHA-256 fields are the
normal artifact identities already used by the workflow to bind a saved result
to its exact inputs and to detect transfer or replay mismatch. The corrected
Dev3 transfer used ordinary file-count/byte-count checks followed by the native
seed and paraphrase validators. Git pins, manifests, and native validation are
sufficient here.

## Why PaperBench has many more rubric criteria

PaperBench starts from a hierarchical paper-reproduction rubric. The code-dev
loader selects implementation-relevant leaves, flattens each leaf into an
independent binary criterion, and propagates normalized ancestor weights. The
three Dev3 tasks contain 50, 70, and 151 master-rubric leaves. Across corrected
Results20 the observed count ranges from 36 to 872, with median 89.5 and mean
183.6. BioMNIBench instead uses compact task rubrics: 6 to 10 criteria, median
6 and mean 6.9.

The difference is therefore evaluation cardinality and prompt size, not raw
dataset bytes. PaperBench Dev3 inputs occupy roughly 10 MiB locally, whereas
the BioMNIBench dataset is much larger on disk. A 306-criterion PaperBench
rubric request measured about 122k input tokens; the 872-criterion smoke used
about 358k input and 18.5k output tokens. That criterion/token expansion is the
reason PaperBench audit work is materially larger.

## Mac feasibility and completed run

The Mac is feasible for a bounded PaperBench Dev3 run. It is not the preferred
Results20 host.

- Hardware during the run: Apple M4 Pro, 12 CPU cores, 24 GiB RAM.
- Largest-task counted smoke: Full and User both completed in 1:09:45, one
  attempt each, reaching `max_revisions`; memory remained healthy and about
  48 GiB disk was free.
- Full revision study: 18/18 in 6:00:14, one attempt each, terminal status
  `completed_scope`.
- Trace-defense request history in the smoke retained successful transient
  retries and four fail-closed contract-exhausted locator repairs; these are
  bounded request failures, not missing or corrupted revision artifacts.
- Audit before the credit stop saved 772 successful provider responses. The
  usage-based estimate is approximately USD 355 (not a provider invoice):
  USD 242.48 Opus and USD 112.53 Sol. Opus rubric scoring alone consumed about
  10.3M input and 494k output tokens.

The machine was not compute-bound; provider latency, token volume, and billing
are the practical limits. A 120-assignment Results20 run would be much longer
than the six-hour Dev3 revision run and substantially more expensive to audit,
so its primary execution should remain on Babel. Mac is useful for Dev3,
smokes, exact resume checks, and provider-free report reconstruction.

## Audit state

Opus has complete evidence for the candidate:

| Stage | Complete Opus evidence |
| --- | ---: |
| Rubric score | 143 semantic records / 188 assignment references |
| Absolute score | 36 assignment references |
| Pairwise preference | 18 semantic records |
| Direct windows | 18 assignments in each of four windows |

The strict read-only extractor rejects Sol rather than emitting partial output.
The preserved Sol gap is:

- rubric score: 19/143 semantic records complete, 124 missing;
- absolute score: 18/27 semantic records complete, 9 missing;
- direct full trajectory: 14/18 assignments complete, 4 missing;
- direct post update: 17/18 complete, 1 missing;
- direct final artifact: 18/18 complete;
- direct final revision: 17/18 complete, 1 missing;
- pairwise preference: 18/18 complete.

Every one of the 124 missing rubric jobs has one preserved failed attempt with
the same provider response: `credit_balance_exhausted` / “You have no credits
remaining.” The missing direct attempts show the same HTTP 429 quota error.
The earlier Opus strict line-count failures were recovered through native saved
response replay; Opus now has all 143 rubric records.

The complete Opus-only candidate means are interim diagnostics, not the intended
panel result:

| Arm | W | S | H | A | S-H | Final-artifact RH |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Full RTT | 84.115 | 66.122 | 70.722 | 34.889 | -4.600 | 0/9 |
| User RTT | 73.793 | 65.979 | 63.301 | 41.111 | +2.678 | 0/9 |

The native two-model comparison remains pending legitimate OpenAI API-credit
restoration. Do not replace Sol, impute it from the 19 completed rubric jobs,
or rerun Opus.

## Source and input identity

- Existing implementation branch:
  `codex/trace-v21-provenance-result20-babel`.
- Revision execution pin: `d68ec3e8729c564ef78de99829fd7931e005de94`.
- Read-only Dev3 analysis pin:
  `d7759eb49fbbe4aa995ff2274b4dc297846534ec`.
- Experiment: `paperbench-code-dev-factorial-r10-4b8d47a6c574`.
- Candidate study:
  `runs/paperbench-rtt-provenance-local-mac/dev3/study/paperbench-code-dev-factorial-r10-4b8d47a6c574`.
- Candidate audit:
  `runs/paperbench-rtt-provenance-local-mac/dev3/audit-sol-opus/paperbench-code-dev-factorial-r10-4b8d47a6c574`.
- Exact corrected input source:
  `/data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260911/dev3/{seeds,paraphrases}`.

The transferred pool has nine native-valid seeds and 15 native-valid
paraphrases: selected neutral variant 0, development neutral variant 1, and
rigorous heldouts 2/3/4 for each task.

## Branch review

No branch was created for this work. No branch is deleted yet:

- keep `codex/trace-v21-provenance-result20-babel`: current PaperBench/RTT owner;
- keep `codex/trace-v21-provenance-dropout-dev3`: active dirty primary worktree;
- keep `codex/harvey-rtt-dev3`: active worktree;
- keep `origin/codex/trace-v21-provenance-result40-babel`: live queued Babel
  Result40 ownership;
- keep `codex/trace-task-paraphrase-local-mac`: merged into the current branch
  but not `origin/main`, so it remains useful provenance until current work is
  integrated;
- `aydan-checkpoint-1` has no remote and is not merged into current/main, so it
  needs content review before deletion;
- local `aydan-red-team` is merged into `origin/main`, but cleanup is deferred
  with the rest of the branch pass after the active experiments finish.

This leaves repository organization unchanged while the surviving branches
still encode active work or unmerged experiment provenance.
