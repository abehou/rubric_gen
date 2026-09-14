# Local Mac execution record

Status at 2026-09-15 07:10 CST: the user-selected local-existing Dev3 run has
completed all 18 candidate revisions. The requested Luna xhigh audit is
terminal with complete rubric scoring, 69/72 valid RH judgments, and 15/45
valid rubric-free judgments. The earlier exact-Babel-input and Gemini attempts
below are retained as chronological provenance, not current status.

## Frozen source and scope

- Latest fetched `origin/aydan-red-team` and local starting commit:
  `571965a9ca8e244477a377649592faec6e46c9af`.
- Dedicated branch: `codex/trace-task-paraphrase-local-mac`.
- Candidate: `attack_defense_v2.1_task_paraphrase_required`.
- Tasks: `da-3-4`, `da-11-1`, `da-18-1`; three replicates; Full and User
  trace arms; 18 assignments; seed `20260806`.
- Candidate experiment identities remain
  `biomnibench-da-factorial-r10-bf6159ff9ade`,
  `biomnibench-da-factorial-r10-7ad21eac3648`, and
  `biomnibench-da-factorial-r10-f7eb5cdbd81c` respectively. Restricting the
  execution audit panel does not participate in those identities.
- The scientific candidate implementation, prompts, model route, revision
  stopping rule, selection, attack, admission, penalties, delivery, simulator,
  solver, and evaluation definitions are unchanged.

## Local adapter and runtime

`run_candidate_local.py` applies an opt-in path-prefix map and local runtime
policy to the canonical YAML. With neither environment option selected, the
existing Babel paths and checked-in capacity policy are unchanged. The adapter
requires absolute non-symlinked inputs, validates the frozen inputs and
compatible control sources before provider work, uses native missing-only
resume, and records input, launch, owner, hardware, config, g1, live status,
and completion receipts.

The local output root is
`/Users/yuenanhuang/rubric_gen_runs/trace-task-paraphrase-required-local`.
The machine-local path map is ignored by Git and has SHA-256
`1e7e4d55a3e8bb869ae30b84c79693f26dd1682fe8e5d28c1b891a7f01c75ca0`.
No Mac absolute path was added to a scientific YAML.

The host is arm64 macOS 26.5 (build 25F71), Apple T6041, with 24 GiB RAM and
12 logical/12 physical CPUs. At inspection time swap use was about 21.8 GiB,
memory pressure reported about 32% free, and the data volume had about 42 GiB
available. The conservative first profile is:

| control | value |
| --- | ---: |
| aggregate provider capacity | 6 |
| concurrent task runners | 2 |
| assignment workers per task | 2 |
| concurrent audit studies | 1 |
| first-run aggregate hard cap | 8 |

The candidate's existing four-thread learning pool is not edited because it is
part of the recorded implementation; the shared six-slot admission policy
bounds its actual provider concurrency. No `SLURM_JOB_ID` or other Slurm state
is synthesized.

## Provider-free verification and Luna route smoke

The exact focused candidate suite passed locally: 53/53 tests (latest run
11.22 s).
The path-map/runtime suites also passed: 107 tests in 6.32 s, with one existing
macOS multiprocessing deprecation warning. Python compilation and
`git diff --check` pass.

Exactly one real same-route `gpt-5.6-luna` Codex turn was executed. It returned
exit code zero and the exact requested `route-ok`, persisted the response and
trace, persisted and reread the session identifier, wrote local capacity
events, and ran with no Slurm identity. The output hashes are:

- `answer.txt`: `4ba908de0e53beffacec4b190ce9d414786aa9c08bb032a366d5ce29eaf683b3`
- `trace.md`: `1d5c1300decd57611a4133c4c0d517242e13f4a99fa727a647132b12774db5ca`
- smoke result: `247253e6b5ec39f070bfcaa73794bc5319db258abafb622bc464e0ed9ad0d4dd`

This was an operational probe, not a benchmark assignment. No separately
billed OpenAI API fallback was used by the adapter.

## Frozen-input inventory

The local `data/biomnibench-da` task snapshot already contains all three task
trees. Their Hugging Face metadata records source revision
`e1c8ca5e11a620087bc48d97888eb69176a1f235`. Full local tree receipts are:

| task | files | bytes | tree SHA-256 |
| --- | ---: | ---: | --- |
| `da-3-4` | 7 | 15,298,827 | `ab01d555e73c330643aaa7c683d4932913f5fdfe94b0f5a6626668fc81287025` |
| `da-11-1` | 16 | 106,283,474 | `4b70dacc328058a892dc149928090095bcc86d1af43fdceda35704232467b51d` |
| `da-18-1` | 9 | 5,054,730 | `369a153e73397c8cd8bc077289550ac64282db3dafccbe439f1e969a8aade1ee` |

The checked-in frozen-input receipt
`experiments/trace-attack-defense-v2/dev3-inputs.json` has SHA-256
`5a846d209bfe52e2a32994a5f4b175e48d28c107da97e291bd106b3c8ad13c94`.
Against it, all 52 `da-3-4` seed files and 12 paraphrase files verify exactly;
all 91 `da-11-1` seed files and 17 paraphrase files also verify exactly.

The BioMNIBench Hugging Face downloader can restore original task data. It
cannot restore these model-produced frozen inputs, so the following are still
required byte-for-byte:

1. `da-18-1` frozen seed root;
2. `da-18-1` frozen paraphrase root;
3. v2.1-compatible source study/g1 for `da-3-4`, producer
   `biomnibench-da-factorial-r10-62e39def3939`;
4. the same for `da-11-1`, producer
   `biomnibench-da-factorial-r10-dddf5e1c5878`;
5. the same for `da-18-1`, producer
   `biomnibench-da-factorial-r10-e44e429b51a6`.

The fail-closed receipt is
`/Users/yuenanhuang/rubric_gen_runs/trace-task-paraphrase-required-local/input-validation.json`.
Its SHA-256 is
`a287a6b6cee373ceb2aed5b2ca99198f331c281022ff12b1519695a321b89da1`;
it records `ready: false` and `provider_calls: 0`. Regenerating any of these
artifacts would violate the canonical frozen-input recipe, so the adapter did
not do so.

## Assignment and audit status

> **Superseded on 2026-09-15 CST.** The exact Babel-artifact gate below records
> the original canonical-lineage check, but it is no longer the execution
> decision. At the user's direction, the candidate is now running against the
> existing local Dev3 task/paraphrase pool, with freshly generated,
> current-format seeds accepted by the current validator. No Babel transfer is
> required for this local development test.

| stage | complete | expected | status |
| --- | ---: | ---: | --- |
| candidate revisions | 0 | 18 | blocked before provider calls by exact inputs |
| candidate audit | 0 | pending judgments | not eligible until 18/18 validates |

Per the latest execution decision, the local missing-only audit will run only
`gemini-3.8-flash`; Sol and Opus are not rerun locally because their work is
already running on Babel. The established compatible development control was
audited by Sol+Opus and has no authoritative Gemini panel. Consequently the
future Gemini candidate results can diagnose the candidate, but are not a
strict same-auditor matched comparison to those control metrics.

No candidate metrics exist yet. The relevant completed User v2.1 Dev3 control
remains W 91.22, S 83.72, H 83.11, A 72.67, W-S 7.50, S-H 0.61, and H-A
10.44. These values are context only and are not evidence about the unexecuted
candidate.

## Next scientific decision

Do not redesign the candidate or run Results20. Once the five exact artifact
roots are supplied from a preserved source, rerun the local input validator,
launch the 18 native missing-only revisions with the profile above, validate
lineage, and then run only the missing Gemini judgments. If those artifacts are
not available anywhere except Babel, the no-Babel-transfer constraint must be
revisited; Hugging Face download cannot produce an exact substitute.

## 2026-09-15 local-existing Dev3 launch

The active experiment uses
`experiments/trace-task-paraphrase-required/local-existing-dev3.yaml` and is
frozen at source commit `571965a9ca8e244477a377649592faec6e46c9af` plus the
recorded uncommitted local execution adapter/config diff. Its experiment ID is
`biomnibench-da-factorial-r10-76e6b92967df`. Scope is exactly the three Dev3
tasks, three replicates, and Full/User trace arms: 18 candidate assignments.
The scientific candidate remains
`attack_defense_v2.1_task_paraphrase_required`; prompts, models, seed
`20260806`, feedback policies, and revision/evaluation semantics were not
changed.

Nine current-format seed assignments completed and validated before the
candidate run. The candidate revision command started at 2026-09-15 00:23 CST
with two concurrent StudyRunners, aggregate provider capacity six, and native
missing-only resume. Generation-1 preparation completed for all three tasks.
At the first recorded live checkpoint, two assignments were running and 16
were pending; both active User-arm trajectories had completed two revision
rounds, and `da-3-4` subsequently advanced to round three without an error.
The local audit remains restricted to `gemini-3.8-flash`, serialized to one
audit study, after all candidate assignment lineage validates.

At 2026-09-15 02:03 CST, the revision study reached 6/18 completed, two
running, ten pending, and zero failed assignments. Persisted state continued
to advance normally; no recovery or scientific change was required.

At 02:53 CST, the same study passed the halfway point at 11/18 completed, two
running, five pending, and zero failed assignments. The active assignments
continued to update their native resume state.

At 03:40 CST, revisions reached 15/18 completed, two running, one pending, and
zero failed. The final three assignments had started or were next in the fixed
execution order; the Gemini-only audit had not yet begun.

At 05:45 CST, a native missing-only finalize pass validated all 18 assignment
records and changed the study ledger to `completed_scope` / `complete`; no
assignment was rerun. The Gemini-only `detect --resume` audit then started at
05:46 CST and loaded all 18 targets, but every attempted Gemini judgment was
rejected with HTTP 429 `RESOURCE_EXHAUSTED`: the configured Google AI Studio
project's prepayment credits are depleted. Zero valid Gemini judgments were
saved. All failure attempts and the completed candidate trajectories are
preserved, and no Sol/Opus fallback or scientific change was made. The audit
can resume missing-only after Gemini credits are restored.

## 2026-09-15 Luna xhigh terminal audit

At the user's direction, the failed Gemini route was replaced by
`gpt-5.6-luna` with reasoning effort `xhigh`; Sol and Opus were not duplicated.
The audit used aggregate provider concurrency four, at most two simultaneous
rubric-score requests, and one audit study. The Mac remained stable. The
candidate implementation and all 18 saved revisions were unchanged.

The rubric-free and RH paths kept their fixed output budgets. Luna exhausted
those budgets without returning structured output for some requests. No output
budget, scientific prompt, or judge definition was changed to improve coverage.

| instrument | valid | planned | invalid |
| --- | ---: | ---: | ---: |
| rubric score, Luna xhigh | 128 | 128 | 0 |
| RH, four windows | 69 | 72 | 3 |
| rubric-free absolute | 3 | 27 | 24 |
| rubric-free pairwise | 12 | 18 | 6 |

The first combined audit exposed a separate execution bug: the full-rubric
judge ignored the xhigh environment override and sent `none`. Those 128 results
remain preserved but are excluded from xhigh metrics. The plumbing now honors
the validated override while retaining `none` as its default, and an isolated
rubric-score-only rerun completed 128/128. Focused verification passes 109/109.

### Partial outcome reconstruction

The local-existing input has four paraphrases: selected variant 0, development
variant 1, and held-out variants 2–3. H below is the mean of those two held-out
variants. A, H-A, and W-A are not cohort metrics because only two final absolute
judgments succeeded.

| arm | W | W_train | S | H | W-S | S-H |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Full | 99.22 | 99.22 | 88.11 | 94.67 | 11.11 | -6.56 |
| User | 93.67 | 93.67 | 95.67 | 93.28 | -2.00 | 2.39 |
| combined | 96.44 | 96.44 | 91.89 | 93.97 | 4.56 | -2.08 |

| RH window | Full | User | combined | invalid | abstain |
| --- | ---: | ---: | ---: | ---: | ---: |
| final artifact | 0/8 (0%) | 0/9 (0%) | 0/17 (0%) | 1 | 0 |
| final revision | 0/9 (0%) | 0/9 (0%) | 0/18 (0%) | 0 | 0 |
| post update | 1/9 (11.11%) | 1/9 (11.11%) | 2/18 (11.11%) | 0 | 0 |
| full trajectory | 1/7 (14.29%) | 2/9 (22.22%) | 3/16 (18.75%) | 2 | 0 |

The 12 valid pairwise judgments prefer the final artifact in 11 cases and the
initial artifact in one. Final learned rubrics contain 23 learned criteria; 13
are `task_required`, active in 10/18 final assignment rubrics (six Full and
seven User criteria). During scoring, task-required criteria were actually
evaluated in nine assignments spanning all three tasks. Concrete obligations
include retaining required LR inference outputs, reporting execution status for
required empirical outputs, matching association metrics to the declared
primary load, and validating required high-level amplification calls. The new
mode therefore activates rather than treating omitted required outputs as not
applicable.

### Luna xhigh cost

Persisted provider usage gives exact observable xhigh spend of `$1.45228805`
across 250 successful responses, including the smoke, rubric-free successes, RH
chunks, and 128 rubric scores. Ninety-four empty-output calls lack a response ID
and provider usage. Estimating their input from recorded request bytes divided
by four and their output as the full fixed budget adds `$0.38115280`, for an
estimated total Luna xhigh spend of **`$1.83344085` (about $1.83)**. The
superseded Luna `none` rubric pass cost `$0.25796065` and is excluded.

### Decision

The run establishes candidate execution and task-required activation, and User
W-S is directionally encouraging relative to the older Sol+Opus v2.1 context.
It does not justify freezing or Results20: A coverage is 2/18, three RH cells
are invalid, Luna is not a matched auditor for the established Sol+Opus control,
and Full S/H calibration is unstable. Wait for the already-running matched
Sol+Opus audit or obtain missing-only judgments under an unchanged judge
definition. Do not redesign the candidate from these incomplete cross-auditor
results.
