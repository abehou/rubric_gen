# Application reasoning-effort diagnostic

Verified failure: fixed low-reasoning Luna and Sol applications both accept the catGRANULE summary contradiction (listed mean0.632/median0.602 versus claimed0.707/0.704). A numerical-check prompt repaired that example but introduced an unsupported proof-demand penalty and reduced admissions. Sol application of Sol-authored criteria also produced no admissions. These results do not test whether additional reasoning helps.

Single change: Luna application reasoning effort low→high, using the original unmodified instructions and schemas. A private process-local provider setting records high effort in the request contract and verifies it in returned request metadata. No edits to the historical runtime checkout. Model, output cap, evidence, criteria, pair preferences, gates, and all outcome auditors remain unchanged.

Use all nine fixed candidate contexts from10377039 and reuse all fresh low-reasoning control applications from10377313 after exact request/candidate/hash validation. Nine cells/57 new application calls only; no proposals, revisions, scoring, or RH audits. Record retries, elapsed time and usage as well as ratings.

Prospective diagnostic endpoints: repair both preidentified factual contrasts without unsupported penalties on the consistent counterparts; retain the controls' three admissions across two contexts and inspect every changed admission against artifact evidence. A diagnostic pass is not a behavioral success and cannot justify production promotion by itself. Stop after this batch if error repair is absent, confined to invented evidence, or offset by erroneous penalties/admission loss. No automatic revision launch and no threshold changes.

Compute: account-free preempt/preempt_cpu_qos, oneCPU,4GiB,45minutes, four cell workers with four native application workers each; global provider limit60 remains enforced. Immutable output /data/user_data/aydanh/rubric_gen/runs/cue-application-reasoning-JOBID.
