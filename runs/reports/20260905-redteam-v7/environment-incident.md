# V7 Python startup incident — 2026-09-05

All times are Asia/Shanghai (CST). This is operational evidence, not a completed
Results20 outcome report.

## Evidence and narrow repair

Around 15:31, new worker startup failed with `ModuleNotFoundError: No module
named 'rubric_gen'` when launching `rubric_gen.runtime.agents.codex_app_server`.
The editable installation metadata and source directory existed, but the
canonical `_editable_impl_rubric_gen.pth` and `_virtualenv.pth` in
`.venv/lib/python3.12/site-packages/` had macOS hidden file flags. The installed
Python 3.12 `site.addpackage` implementation skips hidden `.pth` files.
Fresh imports also failed outside the tool sandbox, without `PYTHONPATH`.

At 15:34:52, only these two verified startup files had their hidden flags cleared.
No source, package contents, dependency version, credentials, proxy configuration,
or historical result metadata was changed. Fresh module discovery passed at
15:37; both files still had no hidden flag at the subsequent check. The actor
that set the flags is unknown. A limited search of formal-run JSONL/log/Python
files found no matching flag-changing command; that absence does not establish
the actor or exclude an external change.

## Impact and recovery status

At 15:37, session 8165 remained live: 66 completed, two running, 27 startup
health failures, and 145 assignments blocked by the provider circuit. All 27
recorded startup failures had the same missing-module error. Circuit-blocked
records are not failed scientific model outcomes. The current invocation's
open circuit does not reset merely because environment imports recover.

After repair, independent current-format validation passed all 66 completed
assignments in 37.18 seconds. All 195 files in the frozen source archive matched
the current workspace. Full recovery has not yet launched: allow active work to
settle, archive the terminal attempt, then use normal `revise --resume`, preserving
valid completed work and using the unchanged protocol. The old completion ETA
is suspended until recovery throughput can be measured.

## Separate protocol event

`da-13-6/rep-001/luna/user-simulator-red-team-artifact`, generation 0009,
recorded an assessment fallback after six attempts. Its final recorded error
rejected artifact IDs, although the input had 15 unique IDs. The prior rubric
and criteria were retained byte-for-byte. This is the existing response-validation
fallback policy, not evidence that unavailable-provider exceptions were converted
to successful rubric generations. Rejected raw responses were not retained, so
the specific malformed output and all earlier attempt causes are unknown.
Retain this event in eventual reporting; do not rerun it away to improve results.

## Recovery launched — 15:45 update

The original session ended at 15:42:36 with 68 completed assignments; all passed
independent validation. Full study/log archive and hash are recorded in the v7
provenance README. Supported recovery session 78150, controller 36019, launched
around 15:43 at concurrency 30 and is producing fresh trajectories/generations.
The 16,543 files of all 68 earlier completed assignments match the archive exactly.

Two assignments failed recovery before dispatch: `da-16-1/rep-001/luna/full-red-team-trace`
and `da-14-8/rep-001/luna/full-red-team-artifact`. Both retain first-turn failure
status, null session/model identity, prompt and no trajectory; current recovery
correctly refuses to infer an executed trajectory but has no reset path for this
startup-error shape. Keep these records, let remaining work continue, then quarantine
the exact failed directories and regenerate only those assignments normally from
valid seeds. No metadata or missing solver output will be fabricated.
