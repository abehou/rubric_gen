# Ranking-policy candidate coverage and reuse gate

Eight additional online admissions from native replay: three assignments previously had no criteria (da13-1rep3, da13-5rep1, da18-5rep2), three had criteria but never penalties (da12-4rep1, da14-3rep1, da18-5rep3), and two had prior penalties (da12-2rep1, da15-2rep3). Thus only three overlap the25assignment stratum identified by adverse aggregate gaps; the intervention must not be sold as covering that entire stratum. Proposed requirements largely address inspectable computation consistency and subgroup fidelity. Actual solver effects remain unknown.

## Verified reuse risk

Frozen cue generation1 records induction implementation d0107bf0286231b7ec01127bae9843e0c7157af0801afa75783a1710641e4b0b. Current offline implementation hash is e1ea7933e3ace5258b338dd876ffcbf12e450950aca23f6e5955695af56b53b6. Current evolution.py differs from cue in policy-aware identity hashing. A subsequent shared admission-code change also affects this identity.

pretreatment_reuse.source_pool checks experiment compatibility and completed source state, but validate_pretreatment_rubric then invokes proposer.elicit_rubric and compares the replayed generation. The cache namespace includes implementation identity. Therefore do not assume explicit source reuse automatically preserves frozen generation1 across this change: direct identity equality is false, and validation may miss the old cache before its final equality check. This inspection is not an executed end-to-end reuse failure and no provider call was made.

Next engineering gate must validate immutable source artifact hashes, source experiment/context, and exact realized starting criteria without generating replacement criteria or rewriting original identities. Record any new consumer verification receipt as new provenance; do not claim the source was produced by current code. If existing native interfaces reject the source, fail before provider calls. No fabricated compatibility, silent regeneration, legacy alias, or historical mutation is acceptable.

The policy remains a candidate, not launch-ready. Resolve and test this gate before the online-only policy implementation and any expensive trace revisions; static/scoring/auditors remain frozen.
