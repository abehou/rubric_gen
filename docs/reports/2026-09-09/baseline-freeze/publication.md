# Publication and conservative cleanup

The accepted baseline checkpoint **9eea696a854c826626eb8c517d26cec3500e1c4f** was pushed to `origin/aydan-red-team` and verified with `git ls-remote`. It is a direct child of the published selected/master correctness fix6234edf. A subsequent documentation/archive commit records the completed cleanup.

## Included

- Accepted scientific source, frozen producing-config snapshots and hashes, selected/master verification, runtime correctness fixes and324 passing provider-free tests.
- All available Full feedback/User simulator × Static rubric/Red-team trace metrics and two plots, with60/60/59/60coverage and missingness explicit.
- Attempted but unaccepted policy reports, including ranking-preservation, active-violation delivery and criterion-update failure/disposition. No new trace policy adopted.

## Retained locally, excluded from the final GitHub branch

179 diagnostic JSON payloads (12,090,123bytes) remain unchanged at their original paths, indexed by SHA256 in [local evidence manifest](../../../archive/baseline-freeze-20260909/local-evidence-manifest.json). All benchmark data, raw trajectories, audit records, shared pools and execution workspaces remain local; no such run/data directories were added to the checkpoint. The298-commit pre-freeze history remains on the local-only branch `archive/aydan-red-team-pre-freeze-20260909` at6719ce3.

## Archived and removed after the push

CPU cleanup job10380691 completed with exit0. Two supplied reference PNGs (733,993bytes) moved unchanged from the root into `docs/archive/baseline-freeze-20260909/reference-figures/`. The unlaunched retention draft is preserved as a patch/test source outside the active method.

Only159 disposable Python/pytest cache files were deleted, freeing3,275,101logical bytes (3.12MiB; not a claim about physical NFS space accounting). All363 top-level run entries were retained; no raw evidence or shared input was deleted. [Exact cleanup manifest](../../../archive/baseline-freeze-20260909/cleanup-manifest.json).

## Publication incident

The first commit attempt failed because Git had no configured author identity, but a non-fail-fast shell continued and temporarily pushed the old6719ce3history, including diagnostic payloads. The error was caught and disclosed; publication was corrected with an explicit lease on exactly that tip to9eea696, preserving the previous published6234edf parent and any unrelated remote work. The final reachable branch excludes those diagnostic payloads; this is not a claim that unreachable GitHub objects have been purged. Subsequent publication uses checked subprocesses and the repository's established Codex identity.

No new experiments or policy optimization were launched. Report-only job10380610 completed in10seconds; cleanup10380691completed. Stop at this checkpoint pending the user's next scientific instruction.
