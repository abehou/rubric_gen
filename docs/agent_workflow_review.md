# Agent instruction/workflow review — 2026-09-05

## Recheck — 2026-09-06 09:58 CST

Reopened the official Astra model guide, AGENTS.md discovery and skill discovery
pages linked below, and inspected the actual root instructions and experiment
skill. The prior instruction-level audit is implemented: focused context routing,
authorized follow-through, risk-proportional verification and historical/current
state separation remain aligned with the current guidance. This is not a measured
Astra performance improvement or a change to model/reasoning settings.

The skill still lives at `skills/rubric-experiments/SKILL.md` and is explicitly
read through root guidance. Native `.agents/skills` discovery remains uninstalled
under this session's protected-path constraints; do not describe it as automatic
discovery. No new skill changes were needed for this read-only recheck.

Result housekeeping subsequently moved private tools to `scripts/diagnostics/`
and grouped unrelated historical outputs under `runs/archive/`. Current path
documentation was updated; archived instructions remain historical evidence.

## Scope and official guidance

Reviewed the repository's root instructions, skill inventory, setup/architecture
and induction workflow, active experiment plan/run index, and recent review/run
records. This is a maintenance-agent workflow update, not a migration of the
experiment's Luna/Sol/Claude/Gemini models or a change to scientific prompts.

Sources checked on 2026-09-05:

- [Latest model / GPT-6 Astra](https://developers.openai.com/api/docs/guides/latest-model):
  clear non-conflicting instructions, authorized follow-through, focused questions,
  risk-proportional verification, and responsive long-running work.
- [Codex customization](https://learn.chatgpt.com/docs/customization/overview):
  small durable project guidance; specialized procedures loaded only when needed.
- [AGENTS.md discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
  and [skill discovery](https://learn.chatgpt.com/docs/build-skills): distinguish
  persistent instructions from reusable skills and their supported locations.

These principles informed the changes below; they do not justify weakening
permissions, forcing subagents, choosing maximal reasoning for every task, or
assuming an instruction edit changes the selected model/runtime settings.

## Findings and changes

| Finding | Change |
|---|---|
| Root instructions repeated log formatting and compatibility constraints but offered no context routing. | Consolidated the rules and added task-specific entry points and risk-based verification. Preserved the user's no-legacy and small-CLI requirements. |
| No repository `SKILL.md` existed. Operational guidance was embedded in an expanding experiment plan. | Added one instruction-only experiment skill covering recovery, monitoring, evidence preservation, and completion. No extra tool wrappers or public commands. |
| Superseded live-process instructions remained inside “Current status”; generic monitoring rules were duplicated. | Marked older checkpoints historical and moved reusable operating rules into the skill. Retained scientific scope and version-specific facts in the plan. |
| The storage-convention paragraph still named the old v7 audit directory. | Corrected it to the configured `20260905-redteam-v7-audit-v2` path. Existing raw outputs were not moved. |
| `AGENTS.md` was part of the immutable 198-file source archive. | Kept the archive unchanged and explicitly recorded the one documentation-only difference; the other 197 files remain identical. |

The scientific method in `docs/rubric_elicitation_workflow.md` stays separate from
agent operations and is unchanged. The active scoring/runtime source, YAMLs,
analysis definitions, credentials, global skills, and Codex settings are unchanged.
Existing provider retry/access issues remain tracked in `CODE_REVIEW.md`; this
instruction cleanup does not fix or conceal those runtime problems.

## Skill discovery limitation

The standard `.agents/skills` directory is protected in this session. Creation
failed both normally and with requested escalation. The skill is therefore saved
in [skills/rubric-experiments/SKILL.md](../skills/rubric-experiments/SKILL.md), and
root `AGENTS.md` explicitly routes experiment tasks to read it. This is usable as
repository guidance but is **not claimed to be native skill auto-discovery**.
Moving it to `.agents/skills` requires permission to write that protected path;
do not bypass this with symlinks or change global discovery settings.

## Verification and limits

- The official skill creator's `quick_validate.py` accepts the frontmatter/body.
- Changed instruction/document links resolve locally; `git diff --check` passes.
- Archive comparison finds only `AGENTS.md` changed among 198 members. Direct and
  generation implementation hashes still match the frozen recorded hashes;
  every semantic-evaluation implementation input is also byte-identical.
- Desk-checked routing: “current progress?” uses read-only state; “continue the
  experiment” resumes authorized work; “change scoring” requires boundary/version
  handling; unrelated documentation edits do not load experiment procedures.

These are structural checks and scenario review, not an independent Astra agent
evaluation or a measured speed/quality gain. No paid model evaluation or full test
suite was rerun for this documentation-only change. Future sessions load the root
guidance according to the host's instruction-discovery lifecycle; current work has
read the edited instructions explicitly.
