# Saved pair preference diagnostic

2026-09-09 15:33 EDT. Provider-free job10375869 completed successfully; original generation records are preserved at `/data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909/pair-orientation-v1/evidence.json`.

For da15-1rep2 generation2 pair_c94a2cf8125fe4dc, deterministic presentation reverses stored artifact order: A is artifact_f85bcdd9c4ed261e and B is artifact_a9eaa02ddac1f735. The saved rubric-free response selects B, and the saved comparison correctly records artifact_a9eaa02ddac1f735 as preferred. This pair shows no A/B parser inversion.

However, rubric-free assessment says A contradicts the 6,436 count and B is consistent; the active/development assessments say the opposite. Independent candidate application also identifies the contradiction in B, while rating A C for invalid supporting computation. These are inconsistent judgments about observable artifact content. A strict support tie can therefore combine different defects with disagreement in the upstream quality preference; broad criterion wording is not yet established as the sole cause.

Provider-free job10375905 checks the actual count mentions and text difference in the two frozen artifacts. No provider calls, revised artifacts, changed criteria, thresholds, or historical judgments. If the original quality preference is unsupported by the raw content, diagnose the pair-assessment stage before another proposer prompt experiment. A single enriched case cannot estimate population reliability or justify replacing the frozen outcome auditors.

## Raw-content verification completed

Job10375905 completed successfully. Both content hashes match their saved history hashes. The artifacts differ only in answer.txt: A states6,436total/3,490up, consistent with its trace; B states6,437total/3,491up while its unchanged trace still says6,436/3,490. Thus the rubric-free judgment reverses the observable difference and prefers the artifact containing the contradiction. Active/development judgments identify the difference correctly. No underlying biological answer or execution is needed to establish this local inconsistency.

This verifies an upstream pair-quality assessment error, not a parser inversion. It can generate a misleading training gap and demand that a consistency criterion reward the worse artifact. Candidate support correctly refuses the saved C/C application; it should not be bypassed to fix erroneous supervision. The invalid-code application is another common defect, not evidence for preferring B.

Next minimum diagnostic: use frozen original pair-assessment requests and artifact IDs, measure factual A/B attribution and order consistency on saved contrasts before changing criterion generation. First enumerate mechanically verifiable single-edit contradictions across saved induction evidence without selecting on static/trace RH outcomes. Preserve all originals. A proposed attribution-focused instruction must be tested only at the pair-assessment stage, with independent checks against literal artifact differences; no expensive trace revision until diagnostic evidence and a separate prospective policy decision justify it. This local finding does not establish prevalence or explain the full Result20 outcome.

Small evidence receipt: content hashes and exact diff (local-only: `docs/reports/2026-09-09/cue-pair-content.json`; hash recorded in the local-evidence manifest).
