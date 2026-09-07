# Selected-reference wiring prerequisite

Implemented; offline acceptance passed. Live checkpoint acceptance is incomplete because automatic approval review rejected the external-payload launch. The neutral-prompt comparison was not dispatched.

## Exact change

[prerequisite-code.diff](prerequisite-code.diff) is relative to the incoming dirty working tree, not HEAD. It contains only this task's 11 implementation/test/documentation files; prior edits are excluded. `git apply --reverse --check` and `git diff --check` pass. Root decision logs are separate.

The old boundary took the master judgment as the score and base-criterion feedback reference while displaying the selected/active rubric. The corrected boundary resolves a judgment of the current artifact under the selected base rubric, independently of the master measurement. It attests the reference's scoring identity, stores its rubric/evaluation/validation hashes, and checks that augmenting that selected base reconstructs the active rubric exactly.

Static: selected judgment → selected score, levels, reasons and displayed rubric → revision feedback or simulator input → stored training score.

Dynamic: selected base judgment → base score and criterion feedback; current active judgment → learned penalties and their feedback. Active base-criterion regrading remains discarded. Training reward is selected base plus learned penalties, clamped at zero. Master judgments remain in `fixed_original_scores` and `canonical_original_score` as independent measurements. The independent audit code and metric definitions are unchanged.

`controller_reference.py` shares resolution, exact reuse and attestation between selected references and master measurements. `feedback.py` rejects a reference that is not the active rubric's base. Both controller recovery and completed-study validation reconstruct the selected-reference bindings. The manifest requires `feedback_reference_protocol: selected-base-plus-active-penalties-v1`.

## Acceptance evidence

- [saved-binding-results.json](saved-binding-results.json): all six predefined saved judgments, 42 criterion bindings, exact score/level/points/reason/rubric-text equality; all six production simulator request payloads and persisted validation bindings checked using an explicitly fake response generator. Zero provider calls for this replay.
- Selected scores by replicate: da-3-4 = 100, 100, 84; da-11-1 = 48, 55, 48. The corresponding historical master scores are 100, 100, 84 and 55, 55, 48. All six mismatched master-reference projections and mixed-reference simulator replays reject.
- Full-feedback and user-simulator controller tests use deliberately different selected/master rubrics and scores, run through two solver turns, validate later checkpoints and completed studies, resume without new judgments or solver/simulator calls, and reject a swapped stored reference and missing protocol marker. Selected scores are 61/71/95 while independent master scores remain 80/55/65.
- Existing dynamic tests retain learned penalty behavior (selected base 60 plus active penalty -4 = 56 even when the augmented judge awards base 100).
- Relevant core suite: 156 passed. Broader execution/experiment checks: [focused-tests.log](focused-tests.log), 249 passed and two unrelated failures: the fixed YAML inventory rejects the six pre-existing development configurations; the fake app-server test cannot bind a Unix socket under the sandbox. These checks were not weakened and no development configuration was removed. Remaining driver checks: [remaining-driver-tests.log](remaining-driver-tests.log), 29 passed, one socket test deselected.
- A whole-suite attempt was interrupted after 88 seconds in the installed autorubric import; 23 tests had passed. This is not a whole-suite success claim. See [pytest.log](pytest.log).

## Information boundary

The full solver receives selected rubric text and selected base feedback (plus active learned criteria for dynamic policies). The simulator receives that same projected payload, the public artifact and interaction history. The simulator-facing payload is hashed and validated on replay; the solver receives only its decision/concerns. Master results are not passed to the feedback projector. Workspace creation still copies only task instruction/data and the submission; no holdout/holistic/RH audit inputs are added. Independent-audit modules, simulator instructions, solver prompt/profile code, initial seed code, revision rendering and stopping methods are unchanged by source comparison.

These checks verify the supplied inputs and code path; they do not assert a new exhaustive audit of all historical solver activity.

## Preservation

[preservation.json](preservation.json) verifies 12,319 pre-existing files under `runs/autonomous-dev3-20260907` and `investigation/autonomous-dev3-20260907`: zero changed, zero missing. [historical-before.json](historical-before.json) contains the individual SHA-256 records. Historical manifests, judgments, results and trajectories were not rewritten. No reserved validation task was inspected. Existing unrelated changes were preserved.

## Live smoke: blocked, not passed

Planned population: da-3-4/rep-001, full-static and user-simulator-static, one real solver turn plus the subsequent scoring/feedback checkpoint per mode. Original minimum 5/maximum 10 stopping configuration was retained; an acceptance wrapper would pause at a durable checkpoint and exercise production recovery. No independent auditors or detectors were to run.

- Initial preparation failed because the inherited pre-treatment source ID no longer matches the newly derived implementation identity. The smoke was changed to construct the static controller configuration directly, with original seeds and rubric files, without rewriting any historical identity.
- Attempt 02 reused one unique historical selected judgment into the two new cases, but the full solver failed before startup because the child received a relative PYTHONPATH. The simulator lacked the repository's existing credential in the private launcher's environment. No revised artifact or new completed judgment was produced.
- Attempt 03 used an absolute PYTHONPATH and loaded the existing credential without printing it. The full case's incomplete failed-turn artifacts were rejected by recovery; they were not repaired by changing metadata. Simulator requests failed with connection errors. Prior failure evidence is preserved, including [smoke-before-resume.tar.gz](smoke-before-resume.tar.gz).
- Attempt 04 would preserve the failed full case and start a fresh full acceptance case, reuse the existing selected judgment cache, and resume only the unfinished simulator case. Automatic approval review rejected this network-enabled command because it considered explicit authorization for the private task/workspace payload to the external Codex/provider destination insufficient. The command did not execute; no alternative route was attempted.

Live totals: 0/2 checkpoint smokes complete; 0 solver revisions; 0 new completed judgments; 1 unique selected judgment reused; no Sol/Opus audit jobs dispatched. The two incomplete acceptance cases remain at their original states under `runs/selected-reference-wiring-smoke-20260907-attempt02/`. They are not study controls. Logs: `smoke.log`, `smoke-02.log`, `smoke-03.log`; launch/source provenance: `smoke-launch*.json`.

## Compatibility and next manifest

Both static and dynamic historical mixed-reference runs are incompatible with the new training protocol. Current resume/validation rejects them; there is no migration, alias or fabricated metadata. Existing completed judgments may be reused only when their exact artifact/rubric/scorer request matches. Sealed seeds and paraphrases remain unchanged and were successfully resolved during smoke preparation. Dynamic checkpoints can require an additional selected-base judgment when the active rubric differs; master measurements remain separate, with exact reuse when compatible.

The 24-assignment review manifest needs revised run/source identities and an explicit selected-reference protocol, while retaining the six candidates, two prompts, two feedback modes and all fixed measurement settings. Its reference to inherited exposure configurations is not sufficient for dispatch: their `pretreatment_source` now fails current identity validation because the existing experiment ID includes the feedback implementation hash. A valid current static execution manifest must be prepared before the next review; old pre-treatment metadata must not be patched. No new pre-treatment generation or change to the study driver was made in this prerequisite.

Keep the code pending live acceptance. Do not freeze the baseline or dispatch the prompt comparison. The remaining approval concerns only sending da-3-4/rep-001 instructions, input data and public submission artifacts to the existing Codex gpt-5.6-luna solver and OpenAI gpt-5.6-luna scoring/simulation services for the two bounded checkpoint smokes.
