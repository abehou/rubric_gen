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

The intended Sol+Opus audit is now complete. After the OpenAI credit issue was
repaired, a missing-only resume retained the old billing failures, reused every
completed Opus and Sol judgment, and dispatched only the missing Sol work. The
strict native coverage checker verifies 18 assignments and 520/520 semantic
judgments across both auditors, with no missing model or judge failure.

The Dev3 result does not support automatic promotion to Results20. Against the
matched static baseline, both auditors report lower RTT W, S, and H means in
both Full and User. The static Results20 baseline remains reusable; if a full
sample is still needed as a paper result, only the latest RTT arm needs to run,
and Babel remains the appropriate host. That larger spend should be an explicit
decision rather than an automatic consequence of this Dev3 gate.

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
- At the credit-stop checkpoint, 772 successful provider responses had been
  saved and the usage-based cost estimate was approximately USD 355 (not a
  provider invoice). The missing-only recovery added Sol work only; a final
  provider-invoice reconciliation was not attempted.
- macOS DiagnosticReports separately show short-lived system-Python processes
  crashing in global NumPy 1.26.4/OpenBLAS. The successful audit owner used the
  repository environment and exited zero, and the final artifact gate passed;
  future local helpers should use `.venv/bin/python`/`sys.executable` with BLAS
  thread counts limited to one rather than bare system Python.

The machine was not compute-bound; provider latency, token volume, and billing
are the practical limits. A 120-assignment Results20 run would be much longer
than the six-hour Dev3 revision run and substantially more expensive to audit,
so its primary execution should remain on Babel. Mac is useful for Dev3,
smokes, exact resume checks, and provider-free report reconstruction.

## Completed audit coverage

The read-only completion gate binds every summary entry to its saved evidence
and verifies both `gpt-5.6-sol` and `claude-opus-5`:

| Stage | Complete semantic judgments |
| --- | ---: |
| Rubric score | 286/286 |
| Absolute score | 54/54 |
| Pairwise preference | 36/36 |
| Direct full trajectory | 36/36 |
| Direct post update | 36/36 |
| Direct final artifact | 36/36 |
| Direct final revision | 36/36 |
| **Total** | **520/520** |

Each auditor has 143 rubric semantic records represented by 188 assignment
references, 27 absolute semantic records, 18 pairwise records, and 18 records
in each direct window. The recovery preserved the original
`credit_balance_exhausted` attempts and recognized six older direct requests
whose immutable provider error code was billing even though the historical
category field said `transient_provider`. No historical attempt was overwritten
and no new Opus request was made.

## Candidate and matched-baseline results

Strict single-auditor candidate means are:

| Auditor | Arm | W | S | H | A | S-H | Final-artifact RH |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Opus | Full RTT | 84.115 | 66.122 | 70.722 | 34.889 | -4.600 | 0/9 |
| Opus | User RTT | 73.793 | 65.979 | 63.301 | 41.111 | +2.678 | 0/9 |
| Sol | Full RTT | 84.115 | 61.574 | 60.058 | 44.222 | +1.516 | 0/9 |
| Sol | User RTT | 73.793 | 56.423 | 56.665 | 46.222 | -0.243 | 0/9 |

Babel jobs `10496503` (Opus) and `10498912` (Sol) extracted the static Dev3
baseline without provider calls. The adapter matched all 18 cells per auditor
by task, arm, replicate, model, and exact initial-submission identity. The
RTT-minus-static means are:

| Auditor | Arm | ΔW | ΔS | ΔH | ΔA | Δ(S-H) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Opus | Full RTT | -2.791 | -10.075 | -2.594 | +2.889 | -7.481 |
| Opus | User RTT | -9.051 | -6.169 | -6.999 | -2.000 | +0.830 |
| Sol | Full RTT | -2.791 | -6.867 | -5.945 | +1.333 | -0.921 |
| Sol | User RTT | -9.051 | -5.438 | -2.213 | -4.000 | -3.224 |
| Two-auditor mean | Full RTT | -2.791 | -8.471 | -4.270 | +2.111 | -4.201 |
| Two-auditor mean | User RTT | -9.051 | -5.803 | -4.606 | -3.000 | -1.197 |

The direct detector is mixed rather than a counter-signal strong enough to
offset the score decline. Across the 18 auditor-assignment votes per arm,
full-trajectory RH positives move from 5 to 4 for Full and 5 to 2 for User;
post-update positives move from 6 to 3 and 4 to 1. Final-artifact positives are
0 in both baseline and RTT, while Full final-revision positives worsen from 3
to 5 (User remains 0). With nine matched assignments per arm, Dev3 is a gate
and diagnostic, not a definitive full-sample estimate, but both auditors agree
on the direction of the main W/S/H deltas.

The retained report artifacts are the `opus-*` and `sol-*` baseline, candidate,
and comparison JSON files under
`runs/paperbench-rtt-provenance-local-mac/dev3/reports/`.

## Source and input identity

- Existing implementation branch:
  `codex/trace-v21-provenance-result20-babel`.
- Revision execution pin: `d68ec3e8729c564ef78de99829fd7931e005de94`.
- Read-only Dev3 analysis pin:
  `d7759eb49fbbe4aa995ff2274b4dc297846534ec`.
- Audit recovery implementation:
  `527246f`, `1f173ee`, `22e1eb1`, and `8f15c82` on the existing branch.
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
