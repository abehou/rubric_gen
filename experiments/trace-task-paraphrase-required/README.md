# Task-required canonical Dev3 candidate

This is the provider-ready configuration for the single structural RTT
revision selected by the 2026-09-13 architecture audit:
`attack_defense_v2.1_task_paraphrase_required`.

It reuses the canonical three-task Dev3 pretreatment/g1 inputs and the v2.1
Full/User conditions. It changes only the version-scoped diagnosis,
compilation, semantic obligation-mode contracts; attack, views, application
(native checks), admission mathematics, delivery, solver, and outcome settings
remain pinned.

The Babel entrypoint remains `run_candidate.sbatch`. Its behavior and paths are
unchanged. The local Mac entrypoint is `run_candidate_local.py`; it supplies an
opt-in absolute-prefix path map and an opt-in local runtime policy while loading
the same canonical YAML bytes. The default local profile is aggregate provider
capacity 6, at most two task runners, at most two assignment workers per task,
and one audit study. Its first-run hard cap is eight. The candidate's existing
four-thread learning pool remains unchanged and is bounded by the aggregate
provider admission policy.

The local adapter must receive absolute `--run-root` and `--path-map` paths. A
machine-local map is expected to live in an ignored runtime directory; never
commit Mac usernames or absolute paths into the scientific YAML. The adapter
validates the exact three tasks, 18-assignment scope, seed `20260806`, candidate
version, frozen seed/paraphrase hashes, compatible control identities/config
hashes, and native g1 availability before it can make a provider call. It then
uses the native missing-only study ledger and writes launch, ownership, live
status, frozen-g1, and completion receipts below the local run root.

`route_smoke.py` is the one-call same-route Luna diagnostic. It verifies an
actual persisted Codex response, readable session state, and local runtime
coordination without a Slurm identity. Run it only as a bounded infrastructure
gate, not as a benchmark assignment.

After all 18 revisions validate, `audit_candidate_local.py` runs native
missing-only detection with `gpt-5.6-luna` at xhigh and does not duplicate the
Sol or Opus work running on Babel. `audit_rubric_score_local.py` is the isolated
rubric-score stage used when completed direct/rubric-free work must remain
untouched. Because the established compatible control uses Sol+Opus, report the
local Luna result as cross-auditor evidence, not a matched control comparison.

The canonical runner still requires its exact frozen inputs. The separate
`local-existing-dev3.yaml` records the user-selected development execution on
the already-present local Dev3 task/paraphrase pool and freshly generated
current-format seeds. Do not confuse that operationally authorized development
run with the canonical frozen-input recipe. Current coverage, metrics, and cost
are recorded in the local Mac execution report.
