## 2026-09-09 — Accepted baseline checkpoint

- 22:09 EDT: Baseline accepted by the user: both static arms have sufficient trajectory/gap signal; wording-only S−H≈0.12 is acceptable, not a remaining baseline blocker. Trace joint mitigation and calibrated artifact RH remain unfulfilled; current scope is checkpoint publication only.

# BioMNIBench completion TODO

Canonical user-directed checklist, 2026-09-09. Update after each completed analysis or experiment. Check scientific claims only against complete frozen Result20 evidence; completed engineering checks require saved-input/source evidence. No desired-direction or provisional checkoffs.

Primary reference: frozen rubric-cue source `0fbe0bbd9acfb8846bb62dbdefa3cfc646c3aa1a`, static10365215/trace10364364. Evidence: [Result20 interpretation](reports/2026-09-08/result20-cue-interpretation.md), [full report](reports/2026-09-08/result20-cue-contrast.md). Preserve simulator, tasks, seeds, scoring and full-trajectory auditors. Stop leakage variants unless necessity is established. Criterion-update revisions10369781 and audit coverage via10370740 are complete; delivery report10369789 and recovered comparison10370774 completed; failed report10369784 preserved. Scientific condition preserved; primary branch remains cue.

## 1. Static baseline signal

- [x] Nontrivial full-trajectory RH:20% confirmed equal-auditor rate (identification bounds20–21.67%).
- [x] Weak-to-strong gap: W−S7.3417points.
- [x] Strong-to-holistic separation exists: H−A11.6500points in the frozen cue rows; S−A11.7667. The user's approximate13.45 is not reproduced by this matched cohort and must not be silently substituted.
- S−H remains a reported secondary endpoint:0.1167 is not clearly positive, but wording-only semantic paraphrases make near-zero legitimate generalization. Per the latest user decision, raising this gap is not a baseline acceptance requirement and does not justify changing the frozen simulator.
- [ ] Detectable lower-frequency final-artifact RH under a calibrated frozen auditor.

## 2. Dynamic improvement over matched static

- [x] Lower full-trajectory RH in completed cue comparison:20%→7.5%; confirmed-rate paired95% interval for difference−22.50 to−4.17percentage points.
- [x] No demonstrated material holistic-quality loss, **subject to uncertainty**: A70.475→70.975, paired95% difference−3.19 to+4.12. This checkbox does not establish equivalence/noninferiority or exclude material harm.
- [ ] Lower final-artifact RH under the same independently frozen calibrated auditor.
- [ ] Primary gaps shrink or at minimum do not worsen; current W−S7.34→9.27 and W−A19.11→20.99 fail the desired point direction.

## A. Final-artifact measurement — no revision reruns

- [x] Inspect artifact routing: frozen RH builder omits the constructed artifact-specific forensic instructions for both auditors;240saved records corroborate monitor route/final-only evidence. Raw wire requests are not archived; see [routing evidence](reports/2026-09-09/final-artifact-routing-check.md). Fix/calibration remains unchecked.
- [ ] Build condition-blinded human-reviewed positive, negative and ambiguous calibration cases from frozen artifacts.
- [ ] Evaluate candidate prompt/routing using sensitivity, specificity, abstention and Sol/Opus agreement.
- [ ] Keep static-versus-trace ordering hidden throughout calibration selection.
- [ ] Select and freeze one artifact-audit prompt and threshold using calibration evidence.
- [ ] Uniformly re-audit existing cue static and trace artifacts with that auditor.
- [ ] Report rates/uncertainty unchanged, including null or adverse outcomes.

Historical model-only diagnostic prompts are not human calibration. Never fabricate human labels. Reuse frozen artifacts and preserve original audit versions; audit-only changes cannot trigger revisions.

## B. Gap behavior

- [x] Verify selected-to-heldout computation/record wiring across all240cue auditor rows: selected identity, heldout2–4, final artifact/model binding, weak-feedback reference and arithmetic pass; [evidence](reports/2026-09-09/selected-heldout-verification.md). Prompt/content validity remains part of the next item.
- [ ] Determine whether static S−H≈0.12 reflects construct or remaining implementation error.
- [x] Predefine next-condition primary gaps W−S and W−A, both non-worsening versus cue static; secondary S−H/H−A and joint RH/quality gates recorded prospectively in [decision note](reports/2026-09-09/cue-citation-policy-decision.md). No outcome success inferred.
- [ ] Complete cue case-level trajectory/gap mechanism analysis.
- [ ] Inspect generation, admission, delivery, active violation assessment, solver response and selected-target conflicts.
- [x] Establish a localized frozen-record mechanism: overbroad provenance prevents20otherwise admissible candidates from passing; native replay verifies this. Behavioral impact remains unproven.
- [x] Propose one isolated policy change after mechanism analysis: online positive-ranking preservation. The earlier citation-precision candidate was discarded after its saved-input diagnostic admitted no criteria; see the ranking-preservation decision note.
- [x] Validate reuse of completed static and compatible frozen starting inputs:20native preparations plus20repeat preparations, then matched source/input gate10371494. New trace outcomes still require complete native validation.
- [ ] Rerun revisions only for modified trace.
- [ ] Evaluate changed trace with frozen scoring/auditors (artifact audit separately calibrated as above).
- [ ] Jointly confirm meaningful trajectory-RH reduction, non-worsening primary gaps and no material quality loss.

Before any revision submission, write a dated decision note: (1)verified failure mechanism, (2)exact single change, (3)reused stages/outputs, (4)why revision rerun is necessary, (5)prospectively specified success criteria including justified materiality margins, (6)stop rule. Do not launch complete workflows for audit/scoring/analysis-only changes.

## Completion

- [ ] All criteria supported together by one coherent matched configuration.
- [ ] Freeze successful configuration.
- [ ] Confirm unchanged at30/45tasks.
- [ ] After confirmation transfer frozen method to PaperBench.

Current exclusive scope is BioMNIBench. No PaperBench or Harvey experiment now. Preserve null/adverse results, all tasks, historical outputs and source identity. Do not select endpoints after candidate outcomes, tune auditors to ordering, or bundle scientific changes.

## Latest completed analyses

- Gap census [report](reports/2026-09-09/rubric-cue-gap-census.md): ΔW+2.383 versus ΔS+0.458/ΔA+0.500; arithmetic explanation, not causal mechanism.
- [da18-7](reports/2026-09-09/rubric-cue-da18-7-mechanism.md): canonical metadata conflicts with instruction; selected auditor disagreement is credit for described versus applied methods. No justified policy change yet.
- [da18-5](reports/2026-09-09/rubric-cue-da18-5-mechanism.md): verified metadata claim contradicts part of holistic auditor reasoning; other methodological concerns remain. Original scores retained.
- [da15-1](reports/2026-09-09/rubric-cue-da15-1-mechanism.md): improved RH/quality precedes the sole learned criterion and no penalty is applied; causal attribution remains incomplete.

Workflow: [minimum-stage rules](reports/RESULT20_DECISION_WORKFLOW.md), [cue branch](reports/2026-09-09/rubric-cue-primary-branch.md). No additional scientific item checked off from these partial mechanism analyses.

- Latest heldout-content check: frozen variants are explicitly wording-only and all20tasks preserve numbering/Levels structure. Near-zero S-H is compatible with that construct; exhaustive semantic validity is not established and the meaningful-positive-gap criterion remains unchecked. See selected-heldout-verification.md.

- Human-review preparation complete: `investigation/artifact-human-review-20260909/reviewer/` contains120blinded frozen cases and blank labels.csv; private provenance map and task-disjoint10/10split are separate. No human labels yet, so calibration-set and auditor-selection checkboxes remain unchecked. Share only reviewer/ with reviewers.

- Review-packet verification passed:120blank label rows,360packet content hashes,10/10task-disjoint split, and no exact task/condition identifiers. Semantic treatment clues may remain in artifact claims; this is masking of metadata, not a guarantee of perfect blinding. Human-review calibration remains unchecked.

- Completed active-penalty census:47/60trace assignments admit criteria,22ever receive penalties (74/484checkpoints). This rules out universal absence of enforcement but does not establish correct violation assessment/delivery; full mechanism item remains open. See reports/2026-09-09/rubric-cue-penalty-census.md.

- da15-2rep3 persistent-penalty case reviewed: evidence-completeness concerns are delivered, not wholly omitted; judge repeatedly penalizes unseen full outputs despite excerpts. Both RH and quality improve in this case, so penalty presence is not a proxy for mitigation failure. See reports/2026-09-09/rubric-cue-da15-2-mechanism.md; mechanism-selection item still open.

- Prospective [artifact calibration protocol](reports/2026-09-09/artifact-calibration-protocol.md) records blinded human review, task-disjoint validation, original versus routing-only candidate, unchanged initial>5 threshold, and uncertainty/abstention reporting. Preparation only; no labels or calibrated auditor yet.

- Completed [admission census](reports/2026-09-09/rubric-cue-support-census.md) and [native replay](reports/2026-09-09/rubric-cue-support-replay.md):455online candidates,288support failures;70have positive support plus tied citations, of which20would pass remaining native gates after hypothetical citation repair. Original decisions replay exactly. This is a verified local provenance failure, not evidence that a new policy improves RH/gaps; no policy-success checkbox is added.

- [da12-4 mechanism](reports/2026-09-09/rubric-cue-da12-4-mechanism.md) documents selected-target pursuit, late admission, and overbroad provenance for an otherwise admissible candidate. One proposed change is an explicit online proposer citation-level check; first test it on saved induction inputs. No new policy condition or success claim yet.

- Completed [criterion-update interpretation](reports/2026-09-09/criterion-update-interpretation.md): no joint improvement over its score-disclosing static control (RH18.33→19.17%, W−S8.525→9.558, A70.192→69.650, uncertain intervals; starting criteria differ12/20tasks). No completion claim or promotion; return to cue.

- Latest execution checkpoint09:12EDT: all prior scientific/audit/report jobs terminal, complete comparison10370774 saved under comparison-v2. Four saved-input citation diagnostic contexts prepared; no new provider diagnostic or revision job submitted. [Decision note](reports/2026-09-09/cue-citation-policy-decision.md) governs the next action.

- Completed [citation diagnostic](reports/2026-09-09/cue-citation-diagnostic-result.md), job10370826:8/8cells,96successful calls,0failures,74seconds. Both fresh control and clarification admit0criteria; stop this prompt candidate before revisions. Exact saved-candidate validation repeat is the minimum next diagnostic to distinguish proposer variability from application instability.

- Uncalibrated artifact-routing candidate passed non-provider real-artifact checks10370831 for both Sol/Opus serializers; same evidence/numerical schema/output budget and other windows rejected. Candidate remains private/unselected; human review and calibration checkboxes remain open.

- Completed [exact-input validation repeat](reports/2026-09-09/cue-validation-repeat-result.md),10370858:62/70level agreement;8changes;2/4fixed citation repairs retain admission eligibility. [Case diagnosis](reports/2026-09-09/cue-validation-contamination.md) verifies a criterion application using a base-rubric target instead of internal consistency. Citation prompt candidate remains stopped; next is a fixed-input context-isolation diagnostic, not revisions or a scoring change.

- 09:46 EDT: Completed [context diagnostic](reports/2026-09-09/cue-application-context-result.md),10370981:88successfulcalls,15/70levels differ. No production change or mitigation claim; exact artifact-code adjudication is next.

- 09:50 EDT: [Consistency adjudication](reports/2026-09-09/cue-consistency-adjudication.md) verifies actual artifact contradictions alongside a wrong-source judge rationale; no authoritative human label or mitigation claim. Next inspect final admitted-criterion application and solver response, not another generic verification prompt.

- 10:02 EDT: [Terminal census](reports/2026-09-09/cue-terminal-penalty-census.md) limits final regression to1/60; [coverage join](reports/2026-09-09/cue-coverage-gap-join.md) locates adverse gaps among25criteria-but-never-penalized cases. Descriptive, not causal; inspect criterion relevance and application in adverse/favorable cases before policy choice.

- 10:08 EDT: [da14-8 coverage analysis](reports/2026-09-09/cue-da14-8-coverage.md) verifies relevant criteria generated but unadmitted; existing distribution criterion does not directly cover panel/direction target pursuit. Blocking-pair validity and favorable-case comparison remain open; no new policy selected.

- 10:15 EDT: [Margin screen](reports/2026-09-09/cue-margin-failure-screen.md) motivates [one prospective admission diagnostic](reports/2026-09-09/cue-ranking-preservation-decision.md). No native changed replay or behavior run yet; no success checkbox added.

- 10:23 EDT: [Native ranking replay](reports/2026-09-09/cue-ranking-replay-result.md) completed:8eligible online hypothetical admissions,3offline gains outside scope. Prior screen all-online wording corrected; no behavioral outcome or success checkbox. Next candidate inspection, online-only verification and starting-material reuse gate.

- 10:28 EDT: [Candidate coverage/reuse gate](reports/2026-09-09/cue-ranking-reuse-gate.md) verifies3of8potential admissions overlap never-penalized stratum; current offline identity differs from frozen cue. Honest source validation before provider work remains required; no reuse or policy-success box checked.

- 10:23 EDT: [Real frozen-input validation](reports/2026-09-09/cue-frozen-input-validation.md) passes20/20sources without providers or mutation. Full study integration/history rebuilding/receipt pinning is still required, so reuse/behavior completion boxes remain unchecked.

- 10:29 EDT: [Frozen input integration](reports/2026-09-09/cue-frozen-input-integration.md) passes20native preparations and20unchanged repeats with provider calls forbidden. This establishes starting-input reuse; full modified-condition launch/scoring compatibility and policy validation remain pending.

- 10:40 EDT: Ranking-preservation trace-only test10371501 is running after matched input/source gate10371494; experimentcd5035b709b4, frozen source1314fac. No completed scientific criterion checked from launch; next monitor revisions, audits, and compare all60matched assignments to completed cue static.

- 10:49 EDT: Prepared private `investigation/cue-joint-gates-20260909/evaluate.py` to calculate the previously specified joint gates from complete report rows, including the one-sided95% quality bound. Synthetic checks cover joint success, exact−2quality-boundary failure and missing coverage rejection; no new scientific outcome evaluated. Owned10371501 remains running and10371512 waits on its dependency.

- 10:51 EDT: Provider-free joint-gate/exposure job10371561 queued afterok10371512,1CPU8G30min account-free preempt CPU. Frozen helper keeps original trace and ranking trace separate; output comparison-v1/joint-and-exposure-10371561, source7cf984a; no new scientific result or revision work.

- 12:09 EDT: Ranking10371501 completed60/60revisions and entered detect-1 in the same allocation; no separate revision-recovery job. PaperBench10372604 capacity gate passed87,135,025hydratedbytes estimate against400,093,609,984freebytes with180GiBother-workreserve; native download active. BioMNIBench10372571 has25/45tasks hash-verified (original20plus5additions).

- 12:34 EDT: Completed ranking Result20 comparison10371512 is adverse: RH33.33%versus static20%/originaltrace7.5%; W-S8.633/W-A20.092versus static7.342/19.108,A70.825versus70.475. Fails prospective RH and primarygap point gates; do not promote/scale; exposure10371561pending, all outcomes preserved.

### Completed ranking-policy assessment

- [x] Evaluate the isolated ranking-preserving admission change on all60Result20 trace assignments against frozen static/original trace, including exposure and prespecified task-paired gates.
- [ ] Establish joint policy success: **failed**; RH33.33% versus static20% and originaltrace7.5%, WS/WA worse than static, holistic noninferiority unproven.
- Next: inspect the22assignments with newly positive auditor observations, including admission/delivery timing and actual solver behavior. Preserve all outcomes; do not promote this policy.

### Active-violation delivery candidate

Original-cue exposure analysis complete:22/60assignments,71nonterminal checkpoints, with both redundant and genuinely omitted assessed concerns documented in `reports/2026-09-09/cue-active-violation-exposure.md`. No completion criterion is checked from this diagnostic. Next implement one opt-in requirement note, verify frozen control behavior and native validation, then freeze a trace-only run under the prospective decision note.

## 2026-09-09 Active-violation Result20 completed analysis

All60keys recovered and audited; native coverage passed. Active-violation delivery produces21.67%full-trajectoryRH versus20%static and7.5%originaltrace; finalartifact0%allthree underexistinguncalibratedauditor. Equal-auditor gap point estimates improve (W−S≈5.90 versus7.34static; W−A≈18.38 versus19.11static), but RH reduction fails. Do not check off jointsuccess or scale this candidate. Delivery confirmed42notes across20assignments/472prompts; next analyze why this actual exposure fails to retainRHreduction, keeping simulator/auditors frozen.

- 16:03 EDT: Pair-attribution clarification rejected after36saved-input calls: lowerorderagreement37/51vs42/51, verifiedwrong-sourcequote. No criterion checked; static/gap/quality/RHjointsuccess remainsunestablished. See reports/2026-09-09/cue-pair-attribution-result.md.

- 16:30 EDT: Single-pair andtable-orderdiagnostics do not establishrobustsupervision: alignedagreement7/10,repeatvariability2/10unchangedrequests. No newcompletioncriterion; policyrevision remainsgated onusefulmechanismevidence.

- 17:00 EDT: Atomiccriterionscope diagnostic failed0/3admissionvs1/3control; no jointscientificcriteriaadvanced. Originalcuebaseline/static andoutcomeauditorsremainfrozen.

- 16:58 EDT: Authorized Sol pair-assessment diagnostic completed18calls: order agreement46/51 versus42/51Luna, with5disagreements remaining. Native replay10376905 passes9contexts and changes induction opportunities13→16; downstream matched induction preparation10376939 is active. These are mechanism diagnostics, not RH/quality outcomes; no completion checkbox advances.

- 17:06 EDT: [Sol-supervision result](reports/2026-09-09/cue-sol-supervision-result.md):2admittedcriteria in1/9contexts versus0/9control, confined todiscoveryanchor;18cellscomplete. No policy/RH/gapcompletioncriterion advanced; diagnose frozen applications before anynewrevision.

- 17:14 EDT: Hash-verified application errors documented in [application diagnostic plan](reports/2026-09-09/cue-sol-application-plan.md); provider-free validation10377249 pending. No policy-success criterion advanced; all candidate/pair/revision/outcome stages reused unchanged.

- 17:22 EDT: [Application model comparison](reports/2026-09-09/cue-sol-application-result.md) complete: Sol3admissions/2contexts equalsfreshLuna; arithmetic error remains. No completion criterion advanced andno modelpromotion; fixed-artifact prompt diagnostic is the next candidate, not revisions.

- 17:35 EDT: [Numerical-check application result](reports/2026-09-09/cue-application-check-result.md): arithmetic detection repaired but admissions decline2/1context versus3/2control; no completion criterion advanced. Candidate stopped before revisions; investigate scope and protected margin failures using frozen evidence.

- 17:54 EDT: [Full canonical admission census](reports/2026-09-09/cue-admission-census.md) verifies all60traces; own-citation support is the dominant bottleneck, not missed bundles or inherited replacement coverage. No completion criterion advances; next candidate is bounded training-only refinement feedback, not gate relaxation.

- 18:08 EDT: [Training-feedback refinement](reports/2026-09-09/cue-support-refinement-result.md) fails its advancement gate:0/3contexts admit criteria, with no runtime failure. No completion criterion advances; model comparisons so far have not isolated criterion-generation model strength.

- 18:20 EDT: [Sol criterion-generation comparison](reports/2026-09-09/cue-sol-induction-result.md) yields0/4admissions under unchanged Luna validation; no completion checkbox advances and no model promotion.

- 18:29 EDT: [Conditional Sol application result](reports/2026-09-09/cue-sol-conditional-result.md):0/4admission contexts despite13/60changed ratings; no completion criterion advances. Outcome auditors and primary rubric-cue controls remain frozen.

- 18:35 EDT: [Reasoning-only diagnostic](reports/2026-09-09/cue-application-reasoning-result.md) repairs arithmetic but loses one criterion admission; no promotion or completion checkbox. Read-only lost-support inspection follows.

- 18:39 EDT: [Canonical filtering verification](reports/2026-09-09/cue-filter-data-result.md) confirms false no-removal claim and inconsistent application of identical filtering code. No criterion outcome/score is rewritten; application robustness remains unresolved.

- 18:46 EDT: [Reason-first diagnostic](reports/2026-09-09/cue-application-order-result.md) fails factual gate despite unchanged admission total; no policy promotion or scientific completion checkbox.

- 18:51 EDT: [Semantic census/bound](reports/2026-09-09/cue-semantic-census.md) finds36mixednonredundancy vetoes but at most3newadmissions after other gates. Defer semantic-stage rewrite; no scientific completion box advances.

## Latest user decision — full-feedback provenance and baseline freeze

The rubric-cue user static baseline is provisionally accepted: trajectory RH20%, W−S7.34, H−A11.65, W−A19.11, A70.48. Preserve simulator disclosure, tasks, replicates, seeds, scoring and auditors. Before any policy variant, compare earlier full-feedback arms against cue by actual inputs and executed code; reuse scientifically identical arms regardless of experiment labels. Run only missing matched arms. Remaining primary policy target: retain original trace RH reduction20%→7.5% while eliminating W−S/W−A regressions without material holistic loss. Artifact calibration stays audit-only. No new completion checkbox is justified by this decision.

- Provenance decision complete: [full-feedback reuse evidence](reports/2026-09-09/cue-full-compatibility.md), job10379227. Reuse earlier full-static; earlier trace differs in sidecar/induction inputs. Native gate10379252 validates all shared inputs; only missing full-trace10379267 and dependent report10379269 submitted. No new scientific success item checked.

- Latest completed analysis: [provisional59matched full-feedback results](reports/2026-09-09/cue-full-provisional59.md), audit10380169/report10380215. User explicitly omitted the one infrastructure-failed pair to obtain a quick check; no60/60completion claim. Trace trajectoryRH26.27%vsstatic21.19%, WS/WA adverse pointdirections, A noninferiority not established; no new success boxes checked. Existing user-simulator60case evidence remains separate and unchanged. User will decide next steps; no further experiment launched.
