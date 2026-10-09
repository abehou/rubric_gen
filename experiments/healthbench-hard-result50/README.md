# HealthBench Hard Result50

Complete:50 official HealthBench Hard tasks ×8 conditions ×3 replicates =1,200
trajectories, with3 revision rounds and complete independent audits. All eight
conditions have150 assignments; no task or replicate was removed from the table.

- [Results table and case corrections](RESULTS.md): W/S/H/A, signed gaps and all four RH windows.
- [Assignment-level results](results.json): all1,200 rows, original/corrected endpoints,
  revision W and original RH model scores/decisions.
- [Task membership](manifest50.json), [configuration](extension.yaml) and
  [correction decisions](corrections.json).

Solver/W use5.6Luna low; RTT uses5.6Luna high; S/H/RH use6Luna high;
A/pairwise use6Sol high. H averages three heldout paraphrases. Saved-evidence
corrections change157 criterion decisions and18 RH-window labels; W/A and solver
answers remain unchanged. The original0–10 RH model scores are retained, not
replaced with invented manual intensity scores.

New30-task independent audits completed2026-10-06 for$23.735758915 in recorded
known token charges;11 unknown reservations total$0.137669625 separately.
Offline correction/recomputation/publication made no additional API requests.
The full local run artifacts remain under
`runs/healthbench-hard-result50-extension-20261006/`; only reports, compact
measurements, configuration and private experiment scripts are published here.

## Revision-stage record

Completed2026-10-06 at13:16PDT. Native offline validation passes all720 new
revisions; together with the480 retained revisions, coverage is50 unique source
tasks ×8conditions ×3replicates =1,200 terminal trajectories (150 per cell).
New preparation is90 seeds/150 paraphrases/30 shared pretreatments. All known
requests used5.6Luna, with the original low solver/W and high RTT effort settings.
No new independent audit was launched.

The new30-task run's recorded token charges are$53.14807891, including recovery
$13.42772572;91 unknown-usage reservations remain$67.37431170, so the conservative
ledger is$120.52239061 with zero pending. Reservations are not a verified invoice.
The user-reported provider bill$42.10 is the pre-recovery snapshot. Known charges
fall inside the original$50–80 forecast (central$58.2); recovery took3h06m22s
versus the3–4h forecast. Final invocation:
`runs/healthbench-hard-result50-extension-20261006/invocations/20261006T170954Z/receipt.json`.

Approved2026-10-06: retain the completed20-task/eight-condition cohort and add30
official HealthBench Hard tasks ×8 conditions ×3replicates ×3revision attempts.
No independent S/H/A/pairwise/RH audit is launched by this runner.

`manifest50.json` lists all50 source tasks. The30 additions are theme-stratified
from the previously prepared80 without outcome filtering; six prior Dev3 source
questions are included, with new configuration-matched trajectories because
their previous prompt/effort settings differed. Their mean criterion count13.33
and prompt length1,454characters are comparable to the original20's13.5/1,792.

`extension.yaml` retains the original Result20 scientific configuration. Runtime
source is copied from the completed Semi/Score-only run's original-prompt source
snapshot, as explicitly requested. Native validation passes720 assignments, and
offline checks confirm unchanged solver/proposer/model/effort/paraphrase settings
and byte-identical original solver/RTT prompt files.

Output: `runs/healthbench-hard-result50-extension-20261006/`.
One shared queue, assignment6/provider12/fanout4/audit0 on the12CPU/24GiB Mac;
memory-pressure availability46% at preparation, no active paid experiment found.
Shared provider admission uses the existing coordination directory, so a future
concurrent experiment must share—not independently duplicate—the12-call cap.
User retains Mac after the disclosed approximately11-hour expectation; planning
range10–14h exceeds the normal two-hour execution target.

Forecast: additional$58.2, planning$50–80, separate hard budget$100. This is not a
forecast for audits and not a guarantee of any RTT/gap/RH outcome. The revision
stage measures online W and saves the natural answers/trajectories; independent
outcomes require the separately deferred audit.

The launcher only runs `seed`, `paraphrase`, and `revise`. The relay permits only
the approved5.6Luna model. Costs use the current official Standard rates and
returned usage including cached input/reasoning output; full source is retained
in the output's `budget_proxy.py`. `budget.json` separates `known_usage_cost_usd`
from `unknown_usage_reserved_usd`; `cost-events.jsonl` records stage, token usage,
actual calculated cost or the conservative unknown reservation. Pending
reservations are not counted as known spend. Invocation receipts preserve stage
start/end budget snapshots and logs; successful calls are retained for native
missing-only resume.

Offline accounting checks cover known/cache token pricing, unknown reservations,
and interrupted pending settlement, without provider probes or paid smoke tests.
The known-usage estimate is token-based accounting, not an independently verified
provider invoice. Existing20-task ledgers and results remain untouched.

At09:27PDT the$100 admission cap stopped the run with523/720 new assignments
complete, known token charges$39.72035 and75 unknown reservations$59.05520.
User then approved continuation and reported provider spend$42.10; missing-only
recovery uses the approved$150 conservative ledger cap, preserving all prior
spending/reservations and archiving the stopped ledger/study. The private runner's
`main(complete_remaining=True)` skips valid preparation and resumes only missing
revisions; it does not launch audit or alter scientific configuration. Incremental
known-cost forecast$15–25, Mac3–4h; continuous monitoring stays in this conversation.
