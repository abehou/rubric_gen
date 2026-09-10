# Canonical dev3 input readiness

All three tasks now have current-runtime-valid input pools (5270c4a), with three saved seed replicates and five sealed rubric variants per task. Canonical randomization remains20260806. The da-18-1 pool is newly generated on Babel, not represented as restored historical Mac output.

| Task | Seed pool | Paraphrase pool | Validation |
|---|---|---|---|
| da-3-4 | runs/autonomous-dev3-20260907/isolation-readers-smoke/seeds | runs/autonomous-dev3-20260907/isolation-readers-smoke/paraphrases |10359297|
| da-11-1 | runs/autonomous-dev3-20260907/baseline-da11/seeds | runs/autonomous-dev3-20260907/baseline-da11/paraphrases |10359297|
| da-18-1 | runs/babel-dev3-da18-inputs-20260908/seed | runs/babel-dev3-da18-inputs-20260908/paraphrase |10359419|

Keep pools separate and immutable. A full matched dev3 comparison can use one task-specific configuration per pool and aggregate all three tasks with complete model/replicate coverage; do not fabricate a combined pool manifest or replace the existing six seeds. No revision/detection condition was executed for da-18-1 during this preparation. The canonical YAML still declares the intended full tier; its original top-level output pool paths are absent, so use explicit validated pool locations when preparing new Babel conditions.

Completion evidence: runs/babel-dev3-da18-inputs-20260908/job-10359419/result.json (both input stages exit0, native validation, unchanged source), completion.json (three seed manifest hashes and paraphrase manifest hash), and prior runs/babel-dev3-input-readiness-20260908/10359297/result.json. Source5270c4a, input launcher81be133,4CPU/128GiB/shared60;elapsed332.43s. No historical outputs changed.
