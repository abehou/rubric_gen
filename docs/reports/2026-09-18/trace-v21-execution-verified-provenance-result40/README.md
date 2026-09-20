# Promoted Red Team Trace Results40 expansion

Status: missing-only revision recovery completed 240/240 valid assignments. The
first Results40 audit owner `10507240` reached the complete source/admission gate
but made no judgment call because the old one-study lease was held by the healthy
Harvey audit. The approved runtime update admits three audit studies and gives
each study independent Sol-60 and Opus-60 partitions (120 total); Results40 will
resume missing-only after that provider-free migration. Its Gemini-only pass uses
the same study owner and a separate 60-request partition.

The source starts from `770aa64d75645310cc9a9706fdc8744b76e371e5`. The scientific method is frozen as `attack_defense_v2.1_execution_verified_proactive_provenance`; only native task-sharded execution and reporting are being added. Original Results20 artifacts and judgments are reused read-only and will be reproduced from the published machine-readable rows before cumulative analysis.

Large state lives under `/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918/`. Native condition identity requires a six-assignment static study and a six-assignment promoted-trace study for each task; both read the same seed/paraphrase roots, and the completion gate checks all four condition hashes. Ten shards × six workers preserve revision aggregate provider concurrency 60 and internal RTT fanout four. The final audit adds `gemini-3.8-flash` without changing any scientific trajectory or scoring prompt: Sol and Opus retain independent 60-request partitions in the core pass. After the long original20 inputs exceeded Google's 20M input-token/minute quota twice with four Gemini workers, missing-only recovery uses two executor workers inside the unchanged 60-slot provider partition. The original20 receives new Gemini judgments too, so cumulative40 supports the requested Sol+Opus, Gemini-only, and equal-weight three-model tables without recomputing the published original20 Sol/Opus judgments.

The audit owner requests 32 CPUs, 64 GiB and an 8-hour missing-only window. This replaces the staged 256-GiB/48-hour request after the completed Results20 audit measured only 4,667,944 KiB peak RSS; it changes scheduling and recovery only, with more than a 13× memory margin. Provider concurrency and every judgment definition remain unchanged.

The recovery source at `36335cf` changes execution recovery only: it archives response-free or incomplete failed turns, verifies matching saved session/status evidence, and reconstructs missing derived snapshot metadata only when persisted workspace and trajectory hashes match the completed turn. Prompts, models, task membership, scoring, and the promoted RTT method remain frozen.

Old20 static YAMLs retain historical relative task and output paths. The execution-only path map resolves those recorded locations to the verified canonical BioMNIBench NAS8 data and preserved home-based Results20 studies after the semantic experiment ID is derived. A focused fix makes the existing opt-in mapper apply after relative paths are resolved; without the opt-in environment variable, path handling is unchanged. The original YAML strings, experiment IDs, study records, prompts and judge semantics remain unchanged.

Current code re-derives different IDs for the two exact historical static YAMLs. Their Gemini audit therefore uses each completed native `study.json` as the identity receipt: the recorded source path, experiment ID, seed root and paraphrase root must validate, and every selected static assignment must be a completed member of the receipt's four-condition ledger with matching task, replicate, solver and condition metadata. No historical receipt or YAML is rewritten.

Provider-free verification `10500847` passed 38/38 focused runtime, identity, candidate and audit-partition checks. The missing-only recovery owner uses two shard workers with one assignment each; its Slurm allocation was right-sized to 4 CPU and 32 GiB to fit currently idle `fnsw` capacity without changing scientific or provider concurrency.

Recovery exposed an execution-only performance defect: `StudyRunner` fully validates every artifact and workspace before marking an assignment completed, while the private Results40 owner repeated that full hash scan for all six assignments in the shard. The duplicate scan consumed several hours and terabytes of logical reads without making a provider call. The completion check now reopens the six terminal sources through the exact audit-target identity/state loader; native per-assignment full validation remains the prerequisite for the completed ledger state. Provider-free compute test `10506919` passed 12/12 checks with the frozen config bundle. No prompt, model, condition, artifact or scoring behavior changed.
