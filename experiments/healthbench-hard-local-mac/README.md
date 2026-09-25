# Local HealthBench Hard Dev3

User-approved scope on 2026-09-25: Full/User simulator × Static/Red-team trace,
three tasks, three replicates, three revisions, all roles gpt-5.6-luna (36 assignments).
This uses the ordinary red_team_trace policy supplied by the benchmark integration;
no execution-specific BioMNIBench defense recipe is selected.

The clean runtime was cloned from origin/codex/healthbench-researchqa at
b89b638ba80338104d618ce90f472f4315a6aefe into
/private/tmp/rubric-gen-healthbench-live-20260925. Downloaded official Hard data
produced data/healthbench-hard/live-dev3-20260925-v2; the native loader validates
36 assignments with the requested models and rounds. Persistent outputs are
runs/healthbench-hard-local-mac-20260925-v2; the temporary runtime must remain available.

The corrected .env.local OPENAI_API_KEY ending IfoA passes a real Luna request.
The first smoke exposed penalty-level ordering in dataset conversion (fixed in
1ee9e12a); the second exposed missing app-server login (fixed in b89b638b).
Previous attempts remain preserved. Smoke invocation 20260925T210750Z completed
three revisions (219 seconds) and all seven audit stages with zero missing or
failed judgments. Main invocation 20260925T211220Z launches all 36 assignments.

After credential correction and a successful minimal end-to-end acceptance run:

```sh
.venv/bin/python experiments/healthbench-hard-local-mac/run_local.py --expected-key-suffix CONFIRMED_SUFFIX
```

The launcher passes that same key to hosted OpenAI and CODEX_API_KEY, omits other
provider keys, runs stages with native resume, and writes command/exit/log receipts.
Mac profile: one outer queue, six assignments, provider cap twelve, fanout four,
audit twelve; machine observed as 12 CPUs/24 GiB with 44% free memory.
The measured smoke suggests a full-run ETA of 20–40 minutes.
The earlier two-static-condition $1–$3 estimate does not cover this four-condition
scope; $5–$15 is a provisional planning range, not a measured price or spend cap.
