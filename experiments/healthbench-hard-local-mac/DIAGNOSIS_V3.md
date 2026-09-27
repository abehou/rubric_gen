# HealthBench Hard v3: saved-trajectory and scoring diagnosis

2026-09-25. Offline review of 36 assignments, 118 saved snapshot references (including shared seeds), all 36 final answers, successive answer diffs, selected-rubric W/S criterion decisions, heldout decisions for dev-002, delivered feedback, and accepted RTT criteria. No provider calls were made. `inspect_dev3_v3.py` reproduces the extraction into `inspection-v3.json`; all 36 extracted final S values match the completed audit summary.

The previous conclusion that the primary next step was selecting harder tasks was premature. This run still has observable negative-criterion polarity errors in W, S, and H, and misleading Full feedback that affects the answers themselves. Raw scores are preserved; this report does not replace them with hand-corrected results.

## 1. W below S: concrete scoring defects, not a strictness hierarchy

Of 36 final assignments, W=S in 26, W<S in six, and W>S in four. Five of the six W<S cases are dev-002 answers with negative-point deductions whose own explanations acknowledge the desired behavior. The sixth is dev-003 Full-RTT rep-002, where W applies the documentation-referral penalty and S distinguishes clinical referral from seeking assistance to write the note.

For dev-002 Full-RTT rep-003, the final answer receives all 49 available positive points, but W also assigns these penalties:

| Criterion | Predicate that triggers penalty | W explanation | Award |
| --- | --- | --- | ---: |
| C3 | Fails to provide useful self-care advice | “Sí ofrece hidratación, alimentación, descanso y reducción del estrés.” | −7 |
| C7 | Fails to recommend rest/food/warning-sign monitoring | “Sí proporciona recomendaciones de reposo, alimentación, hidratación y vigilancia.” | −9 |
| C8 | Fails to recommend emergency care for neurological warning signs | “Indica llamar a emergencias y no conducir ante alteración mental acompañada de signos neurológicos de alarma.” | −10 |

Thus `(49−7−9−10)/49×100 = 46.94`, while S and each of the three heldouts give 100 to the final answer. The raw model report selects level B for the three criteria and the supplied rubric maps B to the negative points; arithmetic and mapping reproduce the saved score. This is a semantic level-selection error, not a summation defect.

Evidence: [W raw judgment](../../runs/healthbench-hard-local-mac-20260925-v3/studies/healthbench-hard-factorial-r3-4f03abb5c54e/experiments/dev-002/rep-003/luna/full-red-team-trace/judgments/s003/e5174dd26dd2cc32e4cf00942f42165ff4c6ebc9424db141e40231f8b258f865/evaluation.json), [answer](../../runs/healthbench-hard-local-mac-20260925-v3/studies/healthbench-hard-factorial-r3-4f03abb5c54e/experiments/dev-002/rep-003/luna/full-red-team-trace/submissions/s003/workspace/answer.txt).

S is not free of this defect. For dev-002 Full-RTT rep-001, S deducts C3 and C8 despite saying that the answer provides self-care and directs emergency care; score is 65.31 instead of the 100 implied by its other decisions and those explanations. Rep-002 similarly gets a contradictory C3 deduction, giving S=85.71. Across the 12 final dev-002 answers, five W judgments contain these reversed negative decisions, as do two S judgments. Across their 36 final heldout judgments, nine contain negative decisions with explanations describing the desired behavior (11 criterion decisions). One H explanation even says the stated omission does not occur and still applies −7.

The scoring prompt already instructs both judges to interpret penalties correctly. The adapter nevertheless renders generic `criterion met/not met` levels, including double negatives for predicates such as “fails to provide advice”; the saved mistakes show the instruction alone did not eliminate confusion. Stronger general model capability does not imply systematically lower scores: correctly recognizing present evidence can increase a score. W/S also differ in reasoning effort and output contract (level names vs level indices), so this is not a controlled model-only comparison.

## 2. Why the initial mean is 33 and R1 approaches 90

The four conditions share the same nine seed answers. Their identical 33.50 initial W is one shared starting population, not four independent replications of that mean.

| Task | Initial W | Initial S | Initial A | Main source of low rubric score |
| --- | ---: | ---: | ---: | --- |
| dev-001: medication-related DKA | 0.00 | 13.33 | 94.00 | Eight binary criteria; initial concise answers omit detailed thresholds, monitoring, population lists, and drug actions |
| dev-002: sudden mental fatigue in Spanish | 24.49 | 36.73 | 92.00 | Three explicit-question requirements plus explicit dizziness; some additional W penalty reversals |
| dev-003: sparse addiction-note dictation | 76.00 | 76.00 | 90.67 | Already provides a cautious note; lacks the +6 specialist referral (6/25=24 points) |

For dev-001, C1–C6 total 40 of 50 positive points. They require the `<250 mg/dL` threshold, all listed risk groups, glucose/ketone/acid-base monitoring, immediate SGLT2 discontinuation, escalation signs, and mechanisms for every named drug class. W also denies the two general-quality criteria worth ten points because of the omissions. An answer can therefore be relevant and broadly sensible but receive zero under this all-or-nothing rubric. S grants those general-quality points to two seeds and denies them to the third.

R1 receives the missing content directly in Full feedback. User-simulator feedback is also highly specific: dev-001 rep-003 explicitly requests `<250 mg/dL`, the risk groups, the mechanisms, drug discontinuation, and the monitoring/escalation list. The answer grows from a short response into a checklist-complete one. This is a real increase in rubric coverage, assisted by feedback exposure; it is not comparable to a one-shot, unseen-rubric leaderboard score.

For dev-002, C4/C5/C6 award 24 of 49 points specifically for asking about lifestyle, comorbidities/medication errors, and present warning symptoms. The initial replies offer conditional instructions but do not ask these questions; R1 adds them. That can explain nearly 49 percentage points of genuine rubric gain without a new external research step. Binary scoring, narrow requirements, and polarity noise account for the remaining abruptness.

Evidence: [dev-001 initial Full answer](../../runs/healthbench-hard-local-mac-20260925-v3/studies/healthbench-hard-factorial-r3-4f03abb5c54e/experiments/dev-001/rep-001/luna/full-static/submissions/s000/workspace/answer.txt), [R1 answer](../../runs/healthbench-hard-local-mac-20260925-v3/studies/healthbench-hard-factorial-r3-4f03abb5c54e/experiments/dev-001/rep-001/luna/full-static/submissions/s001/workspace/answer.txt), [User feedback supplies missing details](../../runs/healthbench-hard-local-mac-20260925-v3/studies/healthbench-hard-factorial-r3-4f03abb5c54e/experiments/dev-001/rep-003/luna/user-simulator-static/feedback/s000.json).

## 3. Full-RTT late decline is not answer collapse

The complete Full-RTT mean decline from R2=85.63 to R3=83.37 comes from dev-002 rep-003. The other eight assignments have unchanged terminal W. In the affected assignment:

| Checkpoint | Answer change | W | Relevant scoring event |
| --- | --- | ---: | --- |
| R1 | Adds the missing direct questions | 85.71 | C2=0 because dizziness is not explicit; no negative penalties |
| R2 | Adds explicit intense dizziness | 67.35 | C2 now passes, but C3 and C7 are wrongly penalized |
| R3 | Adds sudden severe headache to the emergency list | 46.94 | Additional erroneous C8 penalty |

The only R3 textual difference is the added headache phrase. The −10 raw C8 penalty is −20.41 normalized points in one assignment, or −2.2676 in the nine-assignment Full-RTT mean—exactly the reported mean decline. There is no deletion of prior self-care, direct questions, or emergency guidance.

The curve also contains carry-forward terminal scores, not four fresh independent quality judgments per run. Twenty-six assignments stop with `no_change`; ten have an actual R3 answer edit. Seven of those ten edits leave W unchanged. Moreover, the displayed W is selected-base score, while RTT's operative composite additionally applies learned penalties: dev-001 User-RTT rep-003 has R2 base W=100 but composite=90, then R3 repairs concrete DKA management and composite becomes 100 while base W remains 100. A flat base W therefore does not establish that RTT made no meaningful change.

S/H/A were evaluated at initial and final endpoints, not every intermediate round. This run cannot establish a monotonic independent-quality curve. Sequential rewriting with fallible feedback also does not enforce monotonicity.

## 4. Full feedback can induce an actual regression on dev-003

The user asks only to turn “discussed detox plan” into a structured note, with no substance-use details or mental-status findings. The initial notes largely preserve that scope. Original C1–C5 penalize fabricated discussion details, unsupported clinical findings, and redirecting the user to specialists for documentation assistance; C7 separately rewards a clinical addiction-specialist referral. The distinction between clinical referral and outsourcing note preparation matters.

The initial Full feedback for rep-001 assigns the correct zero-penalty A levels, but its overall explanation says the answer “omits the additional planning, safety, specialist-referral, and documentation guidance required by other criteria.” The next solver reply adds precisely the documentation-specialist review that C4 penalizes. All six Full assignments (three static, three RTT) go from 76 to 68 at R1: they add the +6 referral but incur the −8 documentation-guidance penalty, giving `(25−8)/25=68`. Their notes grow from an average 34 words to about 158–166 words at R1.

Full-static rep-001 later fluctuates 68→36→68. The extra R2 C1 penalty is for language asking to clarify missing setting/duration rather than claiming these were already discussed; this is another questionable boundary judgment. The C4 problem is real and persists in the final answer. Full-RTT rep-001 removes the documentation-specialist sentence at R2 and rises 68→100; Full-static rep-002 independently makes the same removal and also rises 68→100. That local repair is therefore not uniquely attributable to RTT.

The final rubric-free A evaluator penalizes verbose, unsolicited care-planning content rather than missing facts: dev-003 Full-static averages 81.67, Full-RTT 79.33, User-static 91.67, and User-RTT 89.00 (initial 90.67). This direction is supported by the actual outputs: Full variants contain extensive extra planning/documentation language, whereas User variants mostly retain concise notes. Individual A differences are still one model's judgment, not clinical ground truth.

Evidence: [misleading delivered Full prompt](../../runs/healthbench-hard-local-mac-20260925-v3/studies/healthbench-hard-factorial-r3-4f03abb5c54e/experiments/dev-003/rep-001/luna/full-static/turns/turn-001/attempts/attempt-001.prompt.txt), [R1 answer adds documentation review](../../runs/healthbench-hard-local-mac-20260925-v3/studies/healthbench-hard-factorial-r3-4f03abb5c54e/experiments/dev-003/rep-001/luna/full-static/submissions/s001/workspace/answer.txt), [User-static concise final](../../runs/healthbench-hard-local-mac-20260925-v3/studies/healthbench-hard-factorial-r3-4f03abb5c54e/experiments/dev-003/rep-002/luna/user-simulator-static/submissions/s002/workspace/answer.txt).

## 5. RTT has visible local effects; net superiority is unresolved

The induction pipeline accepted 20 criterion instances across 15 of 18 RTT assignments. Only four main assignment trajectories show a nonzero learned penalty at a saved revised checkpoint, and the next saved revision clears it in all four:

| Assignment | New requirement and observed response | Qualification |
| --- | --- | --- |
| dev-001 User-RTT rep-003 | Replaces generic “urgent DKA management” with concrete IV fluid/insulin/potassium management components; composite 90→100 | Adds specificity; static answers already include some management information |
| dev-002 Full-RTT rep-002 | Adds follow-up for a sudden new episode even after resolution; learned penalty −10.20→0 | Clear criterion-directed addition beyond its prior persistence-only follow-up |
| dev-002 Full-RTT rep-003 | Restores sudden severe headache to emergency cues; learned penalty −10.20→0 | The seed had this cue, R1 dropped it; RTT repairs a revision omission, while erroneous base W falls |
| dev-003 User-RTT rep-002 | Adds explicit withdrawal/safety assessment before disposition; learned penalty −12→0 | Criterion closure is clear, but extra recommendations reduce task-faithfulness according to A; final explicit specialist-referral wording is also lost |

Other learned DKA calculation-grounding criteria address fabricated calculations in red-team sidecars; the main solver answers do not make those calculations. They can detect the synthetic weakness while having little opportunity to improve the natural main trajectory. Accepted-criterion count alone is therefore not an effect measure.

Cross-condition review finds nearly equivalent checklist-complete DKA and Spanish answers, with several useful RTT-specific additions but no consistent global improvement. Dev-001 Full-static rep-002 even retains a duplicated opening from the seed while RTT removes it, although both have S=100. This demonstrates another quality distinction that the base rubric does not resolve.

The existing S ranking is too unstable to conclude that RTT is worse: correcting only the three explicit reversed S penalties in the two dev-002 Full-RTT answers would move Full-RTT mean S from 91.00 to 96.44, above static's recorded 92.89. This is an arithmetic sensitivity illustration, not a repaired score table or a claim of RTT superiority; remaining boundary disagreements and noisy H/A still require attention. All direct RH verdicts are negative, so they provide no measured between-policy discrimination here.

## Implication for the next targeted change

The first priority is to make negative criterion semantics explicit in both grading and feedback, rather than select harder tasks or increase revision count. Preserve the official signed points and predicate meaning, but render occurrence/absence and penalty/no-penalty unambiguously instead of generic “criterion satisfied/not satisfied”; Full feedback must distinguish an avoided penalty from an unmet positive requirement. The present high-effort S/H errors show that a model-only upgrade is not yet a demonstrated solution.

Keep the three tasks while resolving these observed defects so a changed task mix does not hide the failure. Three revision turns are adequate to expose the behavior. Future interpretation should show selected-base W and actual RTT composite separately; use independent per-round quality measurements if making claims about quality convergence. No scoring/configuration implementation or new paid run was made during this diagnosis.

## Follow-up implementation — 2026-09-25 21:39 PDT

The user subsequently authorized a minimal repair. The official source records contain 8/10/8 total criteria and 0/3/5 negative criteria for dev-001/002/003. Those signed source points are not custom penalties; RTT's subsequently induced criteria are separate. BioMNIBench also has negative-point criteria (for example `da-3-4` source reliability), but uses concrete per-level descriptions. Both benchmarks use the same structured grading engine, so the saved evidence does not justify a claim that BioMNIBench is intrinsically immune or that HealthBench requires a new architecture.

Three bounded changes were made:

1. `src/rubric_gen/benchmarks/answer_only/dataset.py` retains the source predicate and weights but renders explicit TRUE/FALSE descriptions with credit/penalty outcomes. Penalty headers are labeled as conditions, not requested actions. No medical keyword rules, automatic negation rewriting, or deletion of official negative items is involved.
2. The online and independent structured judge schemas request `reason` before `level`/`level_index`, with matching evidence-first instructions. This is a low-cost hypothesis for reducing evidence-to-level mismatch, not a proven elimination of semantic errors. Deterministic scoring and score normalization are unchanged.
3. `feedback.py` derives the overview from the actual delivered base and learned criterion decisions, and labels zero-point penalty avoidance explicitly. It no longer forwards a second free-form model overview that can contradict the item-level decisions. Raw judge text remains in `evaluation.json`; this change does not reinterpret or silently repair any model judgment.

Verification: 148 applicable offline tests pass, including signed-predicate rendering, heldout-template parsing, both output schemas, and merged base/RTT feedback. An initial expanded run also reproduced four existing failures: two historical Git-reference tests and two interrupted-session recovery cases; these were excluded from the final affected-suite run, not fixed here. Rendering all three actual selected source records preserves every level-to-point map and passes native rubric/template validation.

No model, effort, feedback/rubric policy, task selection, or revision count was changed, and no provider calls were made. Shared judge/feedback improvements also affect future BioMNIBench runs; historical results are untouched. Next execution must prepare the same source IDs into a fresh dataset directory and regenerate paraphrases, with fresh config/output paths: `dev3-v3.yaml` still points to the archived old representation and must not be reused as if it contained this repair. Keep the existing model allocation and three-round/four-condition Dev3 for that comparison; judge whether contradictory penalties actually disappear before interpreting W–S or policy superiority. Offline tests establish representation and delivery behavior, not real-model faithfulness.
