# Single-pair diagnostic: partial consistency gain, unresolved attribution

10376267completed20calls in32seconds,0reportedfailures; analysis10376273completed. Original full-context controls were reused from10376113. Orderagreement improves6/10to8/10 (nonanchors5/8to6/8), ties remain1/20. This enriched small test does not establish outcome improvement.

The original cross-pair filtering claim no longer appears. However, attribution still fails. Context1original-order A=artifact_feecad652f093ec8 contains the corrected0.640value, B=artifact_84d7ce95a2bad956 contains0.740; the judge assigns those descriptions to opposite letters and prefers B. Context9swapped similarly reverses genotype-PC versus site/platform descriptions despite returning the same preferred ID as the other order. Preference consistency alone conceals an erroneous rationale.

Both errors are consistent with following the artifact table's sorted entry order instead of the pair's A/B reference order: the request constructor preserves globally sorted artifact entries while pseudorandomizing pair presentation. Source verification must compare the exact submitted arrays before calling that the cause. It is not a parser bug. The single-pair candidate fails its stop rule because source misattribution persists; no revision run.

Next minimal diagnostic: verify submitted table order for these cases, then test changing only the two-element artifact table order to match the already-existing A/B references, with identical text, instructions, schema, pair IDs, and bothorders. Reuse the completed single-pair controls. This is an input-presentation hypothesis; a favorable result still needs prospective policy gating before expensive revisions.
