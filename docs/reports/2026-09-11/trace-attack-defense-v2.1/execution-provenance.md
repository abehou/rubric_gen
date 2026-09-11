# Execution and recovery provenance

| Item | Value |
| --- | --- |
| Recipe | `attack_defense_v2.1` |
| Experiment | `biomnibench-da-factorial-r10-5115fffdd1c0` |
| Scientific source snapshot | `f403b4c4a14eca1e9d61ddfc8c6aa323fda02abc` |
| v2.1 guard commit | `621fb7c` |
| Consumer/recovery commit | `c43a921f9f187cda8659304547ec8849a5f5ba7c` |
| Freeze SHA256 | `8637f5e876e59546cb0f36ce406b4ce63bd0591cf250bef8e35a7c0d2e276280` |
| Config SHA256 | `ca8ca3c526707f8b7396f203aca09fc98c1135ca438906292a559ec72d797ca0` |
| Run root | `/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20` |
| Assignments | 120 (60 Full, 60 User) |
| Auditors | `gpt-5.6-sol`, `claude-opus-5` |
| Gemini | deferred; not probed or substituted |

The original v2 producer run remains unchanged at
`/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/result20/`.
The v2.1 consumer imported and provider-free validated 118 completed assignment
records, recovered the two failed assignments only, and assembled a 120/120
cohort. The compatibility receipt is [compatibility-118.json](compatibility-118.json);
its trace-scoped interpretation is [compatibility-scope.json](compatibility-scope.json).

Execution and recovery records:

| Job | Role | Result |
| --- | --- | --- |
| 10394194 | original v2 Result20 | 118/120; two duplicate-title failures, preserved as historical evidence |
| 10397636 | two-assignment recovery | completed the Full/User failed assignments under v2.1 |
| 10397871 | cohort assembly | 118 imported + 2 recovered = 120 |
| 10397939 | consumer validation | 120/120 completed; no compatibility errors |
| 10397985 | first audit owner | rubric/absolute/pairwise completed; direct windows stopped on producer-ID validation |
| 10398066 | direct-RH recovery | completed in 00:26:22; direct windows only; no scientific changes |
| 10398292 | coverage verification | provider-free 240 rows per direct window and complete semantic stages |
| 10399347 | final report assembly | provider-free tables, case packets and README |

The direct-RH source failure was an explicit producer/consumer experiment-ID
validation mismatch in imported manifests. It was outside the transport/provider
failure modes addressed by `fe1c87d3b245f80c745fd2b94452ed287b5aab21`, so that
runtime patch was not copied into the frozen scientific audit. The identity-only
adapter accepted the two explicitly recorded IDs and preserved failed-attempt
evidence; it did not alter RH windows, prompts, models, trajectories, aggregation,
or completed judgments.

