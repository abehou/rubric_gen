# Promoted Red Team Trace Results40 expansion

Status: revision recovery in progress. Pilot and main/recovery owners have preserved at least 234/240 valid assignments; formal audit remains gated on 240/240. Missing-only recovery `10499500` is dependency-controlled behind active owner `10498336`, followed by concurrent Sol+Opus audit `10499502` and provider-free report/cost jobs `10499503`/`10499504`.

The source starts from `770aa64d75645310cc9a9706fdc8744b76e371e5`. The scientific method is frozen as `attack_defense_v2.1_execution_verified_proactive_provenance`; only native task-sharded execution and reporting are being added. Original Results20 artifacts and judgments are reused read-only and will be reproduced from the published machine-readable rows before cumulative analysis.

Large state lives under `/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918/`. Native condition identity requires a six-assignment static study and a six-assignment promoted-trace study for each task; both read the same seed/paraphrase roots, and the completion gate checks all four condition hashes. Ten shards × six workers preserve revision aggregate provider concurrency 60 and internal RTT fanout four. Audit uses one owner with independent Sol-60 and Opus-60 partitions, 120 request workers total.

The recovery source at `36335cf` changes execution recovery only: it archives response-free or incomplete failed turns, verifies matching saved session/status evidence, and reconstructs missing derived snapshot metadata only when persisted workspace and trajectory hashes match the completed turn. Prompts, models, task membership, scoring, and the promoted RTT method remain frozen.
