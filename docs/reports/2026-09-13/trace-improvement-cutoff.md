# Red-Team-Trace improvement: execution cutoff and continuation instructions

**Cutoff:** 2026-09-13 21:26 EDT  
**Repository:** `origin/aydan-red-team`  
**Cutoff commit:** `ad790fbb1766a58ec35130ba5a6ef1c3842bb731`  
**Working checkout:** `runs/babel-code/attack-defense-v2`

This document is the handoff point for the remaining Red-Team-Trace work. It
records what is complete, what is only implemented, and the exact order for the
next scientific calls. It does not create a new scientific baseline or alter any
historical output.

## Scientific status

`attack_defense_v2.1` is the supported incumbent, not a complete joint success.
Its frozen Results20 result is:

| arm | RH full | W-S | W-A | delta S | delta A | interpretation |
|---|---:|---:|---:|---:|---:|---|
| Full | 14.17% | 6.12 | 24.68 | +0.70 | +3.69 | practical Full target passed |
| User | 10.00% | 9.19 | 18.33 | -0.62 | +2.01 | RH improved, but User calibration target failed |

The User problem is the positive W-S and slight S/H loss. Earlier v3, v3.1,
v3.2, R1/R2, D×G, P1/P2 and public-evidence-firewall work is preserved as
diagnostic historical evidence and is not the next parent.

The selected next candidate is
`attack_defense_v2.1_task_paraphrase_grounded`. Its only scientific change is
to pass both the selected/original base rubric and the development-rubric
paraphrase into the existing diagnosis, compilation and semantic-review stages,
with concise task-level, repair-preservation and paraphrase-robust guidance.
Attacker, quality/rubric-view scoring, application, admission mathematics,
penalties, schedule, reminder delivery, feedback policies, solver, models,
settings, stopping and sealed heldout rubrics remain v2.1.

The implementation is in `b66035b`; a test-fixture correction is in `c0aa4a3`;
the readiness/report update is in `ad790fb`. Focused provider-free tests passed
6/6 in job `10431812`. No scientific candidate assignment has run, so there is
no candidate Dev3 result to interpret or promote.

## Operational and cost status

The fresh worker-route smoke `10431507` failed before a model turn with
`CodexProviderHealthError` wrapping `TransportClosedError` during Codex/Luna
app-server startup. This is current runtime evidence, separate from the old
account-limit receipt. The route must pass a small same-route diagnostic before
any batch of model calls.

The shared export `nas8:/data/user_data/aydanh` reported 2.0T used, 15M free and
100% inode use. This is shared NFS headroom, not a verified personal 500GB quota;
the export does not answer the standard `quota` query. Read-only scan `10431744`
timed out after 30 minutes while traversing the large tree. It confirmed
`rubric_gen/validation` at about 124M but did not finish `runs` or `cache` top-
level totals. No scientific artifact, audit record or other owner's data was
deleted.

At the cutoff Slurm snapshot, `10424672` is the only running job (PaperBench,
32 CPUs, separate owner). The other 36 jobs are pending historical PaperBench
or trace dependency chains: 34 trace and 2 PaperBench, with holds or unsatisfied
dependencies. Pending jobs have no allocated CPUs and make no provider calls.
Do not bulk-cancel or duplicate them; preserve their native provenance and
resume relationships.

The visible local cost reconciliation did not prove a `$16,000` Anthropic total.
The pinned trace-v1/v2.1 ledgers total about `$935.88` in usage estimates; a
separate 3,904-row score scan reports `$4,175.05` with unresolved overlap. These
are not an account invoice. Audit/score calls are the expensive stage, so never
launch a large audit batch until outputs are writable, the audit runtime has
passed a representative check, and missing-only resume is confirmed.

## Required continuation order

1. Pull/fetch this branch and read this document, the v2.1 report, the candidate
   report at `docs/reports/2026-09-13/trace-task-paraphrase-grounded/README.md`,
   and the exact candidate source/configs.
2. Run provider-free tests. Preserve legacy v2.1 request identities. Confirm
   that only diagnosis/compilation/semantic candidate requests contain the
   development rubric; attack, quality, rubric-view, application, admission,
   User simulator and Full feedback remain unchanged.
3. Check the current worker route with one minimal same-route request. Do not
   infer availability from an old quota message or from login success alone.
4. Confirm that exact canonical Dev3 starting inputs are available. The Git
   branch does not contain the frozen NFS inputs under the
   `control-v21-compatible` roots. Do not regenerate seeds, paraphrases or g1
   for convenience and do not claim a matched comparison without them.
5. Run the candidate on canonical Dev3 only: `da-3-4`, `da-11-1`, `da-18-1`,
   three replicates, Full and User (18 fresh assignments). Use separate output
   ownership and native missing-only resume. Do not run Results20 during tuning.
6. Before paying for Sol+Opus audit/score calls, validate assignment completion,
   generation lineage, public artifacts, writable output roots and audit setup.
   Preserve successful judgments and rerun only missing/failed judgments.
7. Evaluate W, W_train, S, H, A, W-S, S-H, H-A, W-A; all four RH windows;
   both auditors; abstentions; learned criteria; selected/development pair
   views; reminder exposure; and concrete task-level repair evidence.
8. Reject the candidate and return to v2.1 if S/H/A or RH materially worsens,
   or if criteria remain selected-wording-specific. Do not stack a selector or
   simulator redesign on a failed candidate. At most one separately justified
   selector candidate may follow saved evidence that disagreement pairs are
   systematically missed.
9. Only after a coherent Dev3 signal, run one matched development continuation
   if needed, freeze the exact recipe, and then run one Results20 validation.
   Results20 is for reporting the already validated method, not for prompt
   selection. If that one Result20 meets expectations, stop this improvement
   task; do not launch another variant on the same 20 tasks.

## Explicit non-goals

Do not revive v3/v3.1/v3.2, R1/R2, D×G, P1/P2, public-evidence-firewall,
budgeted delivery, a new simulator/reviewer role, a new audit framework, a new
baseline, a new task set, a new penalty/margin rule, or a Result20-driven prompt
change. Do not fake Slurm variables on a laptop, do not rewrite old receipts,
and do not treat a source checkout without canonical inputs as an experiment.

The final method, if supported, should still be describable in one sentence:

> v2.1 Red Team Trace, with dynamic criteria grounded in task-level relations
> across selected and development rubric paraphrases.

Any provider/storage failure is an operational finding. Preserve completed work,
record the exact missing scope and safe resume command, and avoid paying for
calls whose responses cannot be persisted.
