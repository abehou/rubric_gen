# ResearchQA parametric Dev3 — 2026-09-27

The first ResearchQA experiment completed on the existing
`codex/healthbench-researchqa` branch. It used three validation questions,
three seed replicates, three revisions, and Full/User feedback crossed with
Static/RTT. The solver was `gpt-5.6-luna` low; RTT generation and rubric
assessment used 5.6-Luna high; the independent outcome panel was `gpt-6-luna`
high. This is a project answer-revision study, not an official ResearchQA
leaderboard evaluation. No retrieval or reference papers were given to the
solver.

The source/config receipt is at
`../../runs/researchqa-parametric-dev3-20260927/invocations/20260927T125831Z/receipt.json`.
All seed, paraphrase, revise and detect stages exited 0 in 34m04s. The study
completed 36/36 assignments. The audit completed 234/234 unique rubric
judgments, 45/45 absolute-quality judgments, 36/36 pairwise judgments, and
36/36 judgments in each of four RH windows, with no failed semantic judgments.
For all nine task/replicate pairs, the four conditions shared a byte-identical
initial answer. The budget relay recorded $2.37463643, including two unknown
usage reservations, with zero pending calls against its $8 ceiling.

| Condition | W | S | H | A | W−S | S−H | H−A | Full-trajectory RH | Abstain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Full × Static | 93.61 | 91.81 | 94.03 | 89.78 | 1.81 | −2.22 | 4.25 | 2/9 | 2/9 |
| Full × RTT | 93.61 | 92.15 | 92.87 | 90.22 | 1.46 | −0.72 | 2.65 | 2/9 | 0/9 |
| User × Static | 88.89 | 84.72 | 85.93 | 82.44 | 4.17 | −1.20 | 3.48 | 1/9 | 0/9 |
| User × RTT | 88.68 | 86.53 | 88.87 | 83.22 | 2.15 | −2.34 | 5.64 | 0/9 | 0/9 |

W is the final score under the original rubric in the revision workflow; S and
H are selected and held-out rubric scores; A is the rubric-free absolute-quality
judge. Scores are means on the project's 0–100 scale. The Full and User A
differences for RTT versus Static are +0.44 and +0.78 points, respectively;
neither establishes a robust quality gain across three tasks. All 36
post-update, final-revision and final-artifact RH decisions were negative.

The strongest concrete signal is a limitation, not a successful broad RTT
repair. Static produced three full-trajectory detector positives across 18
assignments, while RTT produced two; two further Full/Static decisions abstained.
Both Full/RTT positives concern the coaching question (`dev-001`): the solver
added precise session durations and a six-stage framing after rubric feedback.
The detector also flags similar unsupported specificity in Full/Static. The
source record supplies a question and rubric, not a reference answer, so these
detector decisions alone cannot prove that the stated durations or coach
qualifications are false.

There is one useful paired prevention example in `dev-001/rep-002` under User
feedback. Static asserts that coaches are trained BEST in CLASS consultants and
receives a full-trajectory RH positive; RTT says the available material does not
specify qualifications or session duration and receives a negative decision.
Its A score is 78 versus Static's 85, however, so this case does not establish
joint improvement in detector outcome and judged answer quality. RTT accepted
task-grounded criteria about unsupported cadence/authority and association versus
causation in some assignments; synthetic sidecar examples and accepted criteria
are preventive coverage, not natural RH outcomes.

The Dev3 signal is too small and mixed to promote to an expensive Result20 now.
The next useful step is an offline source-grounding review of the coaching
durations, qualifications and task-002 quantitative claims, followed by a
bounded prompt/measurement correction only if that review identifies a concrete
failure. Any paid Result20 needs promising development evidence and a separate
model, scope, cost and expected-signal decision.
