# Runtime throughput cleanup

Implementation owner: isolated `runtime-throughput-cleanup` worktree, based on
`fe1c87d3b245f80c745fd2b94452ed287b5aab21` (latest origin at initial fetch).
Active PaperBench 10397534 and BioMNIBench 10398066 sources/output ownership were
left untouched. Diagnostic allocation 10398213 reuses the locked Python 3.12
compute environment. No capacity policy change; aggregate 60, audit studies 1.

## Prioritized incidents

| Priority / actual error | Owning path | Observed cost | Existing repair / remaining common action |
|---|---|---|---|
| P0: wrong imported producer ID for all direct windows | `evaluation/direct.py`, `evidence.py`, `targets.py` | Four direct windows failed before generation; operator delay unmeasured | c43a921 local whitelist adapter; replace with per-assignment producer resolution |
| P0: subset ledger mistaken for full ledger | consumer assembly, `execution_scope.terminal_records` | 10397848/10397864 failed; corrected consumer validator 120/120 in 32s | Restore 240 ledger / 120 selected, including 118 imported + 2 native and 120 pending static; share all readers |
| P0: two assignment workers despite ready backlog | active `paperbench_launch.py:152` | Recovery elapsed includes useful work; avoided delay not isolated | `workers = 2 if args.recovery else 60`; future explicit Dev3 4/8 resource profiles, Results20 32 |
| P0: serial suite plus thread-local audit leases | `commands.run_detect`, decorated stage runners | Measured rubric/free work 2,108 + 600; free stage 3m24s, rubric nearly done at 12m18s | One coordinator owns output/audit lease, explicit internal prepared execution and bounded request executor |
| P0: neutral-policy retry-envelope checker | private `paperbench_checks.pool_evidence` | Delay unmeasured; zero evidence of changed scientific inputs | Failure dictionary used attempt number without criterion ID; exact criterion-014 attempt-2 replay matches all 51 requests |
| P1: serial source loading before futures drain | `detection.runner._prepare_jobs` | Several minutes observed before dispatch; exact breakdown previously unknown | Bounded loading/planning and ready-request dispatch; phase timings |
| P1: false full-rubric response timeout / schema count | full-rubric judge paths | Prior census: ~90 aggregate request-minutes; successful streams 318–1,223s | Retain fe1c87d SSE/inactivity/indexed format/3,600s subprocess fix |
| P1: NFS temporary cleanup / Codex startup | owned filesystem/process lifecycle | Prior census spans include successful work; resource attribution incomplete | Preserve bounded existing cleanup/startup/checkpoint rules; verify completion boundaries |

Recovery 10397636 took 47m50s to complete two real revisions; this is not all
wasted timeout time. Direct panel cardinality is 120 assignments × two auditors
= 240 logical judgments **per window**, with existing physical chunk calls.

## Read-only measurements so far

- Producer/status integrity: all 758 rewritten consumer status files have separate
  inodes; all 758 producer contents match the repair receipt's recorded original
  SHA256. The repair used atomic replacement. No producer content mutation found
  in this inspected set; this does not claim a whole-run forensic census.
- Real NFS source resolution: 240 ledger rows, 120 selected completed assignments,
  118 imported producers, 0.1814s. Existing cache state; not a cold-mount claim.
- Slurm batch high-water RSS at initial inspection: PaperBench 4,184,616 KiB;
  direct recovery 2,150,732 KiB. Retain 256 GiB requests; these two-worker values
  do not establish eight-worker peak requirements.
- Saved neutral-role request: all 51 criterion requests match exact configured
  instructions/evidence when reconstructing the criterion-specific repair suffix.
  No seeds/paraphrases/revisions regenerated.

Implementation and validation are in progress; measurements below will be
populated from executed checks, separately from controlled-provider tests.
