# Missing-only audit recovery with reviewed runtime

The queue2/3 producers retain their original scientific sources (`534e797` and `b97c4fd`). Their failed Opus rubric requests used the v6 nested structured-output representation. `Schema is too complex` is a provider schema rejection, not a scientific verdict or timeout. Other missing cells include bounded incomplete/invalid responses; their exact failed attempts remain saved.

The shared runtime session already reviewed and tested the relevant fix in **c451942**. It replaces nested rubric-response blocks with one indexed string and validates every required criterion and level locally. This changes the output-format instruction/schema; it does **not** change rubric semantics, judge model/settings/budget, target artifacts or the panel. No new recovery framework is added.

Two isolated audit consumers carry exactly that patch:

- **0b58da6**, `/home/aydanh/repos/rubric_gen/runs/babel-code/trace-audit-q2-original-20260912`, parent534e797.
- **9233e64**, `/home/aydanh/repos/rubric_gen/runs/babel-code/trace-audit-q3-reviewed-20260912`, parentb97c4fd.

The copied implementation and focused test files match c451942; **514 tests passed**. Native source resolution uses each original config path. Active producer/audit code is never hot-swapped.

[Queue2 native replay](runtime-replay-queue2.json) accepted all227 existing rubric-score records unchanged: R1 has24 missing scores across its first two tasks, R2 has21; both da-18-1 score stages remain unstarted. [Queue3 native replay](runtime-replay-queue3.json) accepted all346 existing Semi/Score-only fixed rubric-score records unchanged, leaving6 and8 missing respectively. Replay made **zero provider calls**, compared saved record bytes before/after, and used native completed-record adoption rather than rewriting producer metadata.

These counts describe rubric scoring only. Already complete quality/direct-RH stages are preserved by native `detect --resume`; complete full-cell reporting still requires every declared stage. The new wire representation receives its native request identity only for missing judgments. Old successful judgments keep their original v6 request/response records, and old failures are retained. A valid unfavorable score is never retried.

Before any recovery provider call, newly published reviewed descendants f6f0212/8963c90 were incorporated: queue2 consumer **f7019ff**, queue3 consumer **c10b2c2**. These add strict saved-response replay and mixed-provenance coverage validation;160 incremental tests passed, one existing test skipped. Live v8 protocol is unchanged. Native selected/development reuse also validated before heldout generation, with zero provider calls.
