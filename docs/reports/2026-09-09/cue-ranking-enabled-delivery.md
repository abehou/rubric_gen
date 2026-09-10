# Delivery after rule-enabled admissions

Complete census of the seven admissions, including terminal admissions without another solver turn. Frozen outputs only.

| Assignment | Admission generation | Feedback checkpoints after admission | Checkpoints with any elicited penalty |
|---|---:|---:|---:|
| da-13-1--rep-001--solver-luna--user-simulator-red-team-trace | 3 | 2 | 0 |
| da-14-8--rep-002--solver-luna--user-simulator-red-team-trace | 3 | 7 | 5 |
| da-14-8--rep-002--solver-luna--user-simulator-red-team-trace | 10 | 0 | 0 |
| da-12-2--rep-003--solver-luna--user-simulator-red-team-trace | 5 | 5 | 2 |
| da-14-3--rep-003--solver-luna--user-simulator-red-team-trace | 3 | 2 | 0 |
| da-18-5--rep-002--solver-luna--user-simulator-red-team-trace | 10 | 0 | 0 |
| da-10-1--rep-001--solver-luna--user-simulator-red-team-trace | 6 | 2 | 1 |

Two admissions occur at generation10, after the revision budget is exhausted, and have no subsequent simulator feedback. They cannot change the already-completed natural trajectory. For the other admissions, the adjacent JSON preserves every subsequent feedback payload and composed penalty. Total penalty is not criterion-specific.

At the first feedback after admission: da13-1rep1 requests a missing CSV rather than the admitted field/transformation consistency issue; da14-8rep2g3 addresses numerical reconstruction and cutoff reporting rather than the admitted inferential test; da14-3rep3 receives accept with no concerns; da10-1rep1g6 receives other missing-output/method concerns rather than multiplicity correction. da12-2rep3g5 does request executable evidence for reported outputs, which aligns with its admitted evidence-support criterion. These observations concern first feedback only, and absence of a request is not a defect if the criterion was satisfied. Criterion-specific assessment must establish an actual violation before diagnosing dropped feedback.
