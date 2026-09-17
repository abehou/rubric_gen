# Frozen Dev3 execution relocation (NAS1)

This Babel/NAS1 record is historical. Execution subsequently moved to the
local Mac; see [the local execution record](local-mac-execution.md). The Babel
runner and paths below were not rewritten.

This is an operational snapshot for the frozen
`attack_defense_v2.1_task_paraphrase_required` Dev3 candidate. It does not
change the scientific recipe, request identities, task membership, or frozen
inputs.

## Capacity and bounded cleanup

The four directories below were explicitly authorized for deletion. They were
owned by `aydanh` (uid/gid `6011048`) and no running Slurm job or process used
them at the check time. Their bounded byte totals were:

| path | bytes |
| --- | ---: |
| `/home/aydanh/repos/CooperBench-git-r3-20260723` | 54,691,328 |
| `/home/aydanh/repos/CooperBench-next-20260721` | 68,425,216 |
| `/home/aydanh/repos/CooperBench-git-20260722` | 55,223,808 |
| `/home/aydanh/repos/CooperBench-sera-20260722` | 66,606,592 |
| **total** | **244,946,944** |

The protected `/home/aydanh/repos/CooperBench-git-r2-20260723` was retained.
Before deletion (06:49:38 EDT), NAS1 reported 7.1 GiB available and 8% inode
use. After deletion (06:50:40 EDT), it reported 7.3 GiB available and 8% inode
use. NFS accounting fluctuates, so the measured deletion total above is the
space-freed figure; the `df` delta is not treated as an exact accounting
delta. The full probe receipts are in the adjacent Slurm logs
`home-cleanup-probe-10437528.log` and `storage-current-10437391.log`.

The earlier NAS8 check reported a globally constrained `nas8:/data/user_data`
filesystem (about 2.0 TiB, 100% bytes/inodes). That export is not being repaired
or written by this run. It remains the read-only source for the frozen task,
seed, paraphrase, realized-g1, and pretreatment inputs. No per-user quota was
inferred from the global `df` result.

## New execution paths

The old candidate writable roots under
`/data/user_data/aydanh/rubric_gen/runs/trace-task-paraphrase-required-20260913`
and its NAS8 cache are no longer used for new candidate output. The updated
runner writes durable study, owner, completion, live, and audit state under:

`/home/aydanh/runs/trace-task-paraphrase-required-20260914/`

The Slurm wrapper uses `/scratch/job_tmp/$SLURM_JOB_ID` for job-temporary files
and keeps its small launcher log in the repository. Frozen NAS8 paths in the
three YAML files are input/pretreatment producer paths only. The code still
uses the same candidate version, seed `20260806`, three replicates, three
canonical tasks, two trace feedback arms, and 32-CPU runner profile.

## Storage estimate

The exact compatible v2.1 stress tree is on NAS8 and was not recursively
scanned during this cleanup. A measured historical study proxy records 309.2
MiB for 50 completed case directories (mean 6.2 MiB, maximum 34.1 MiB); the
current `/home/aydanh/runs` tree was about 172.5 MB before this run. Even with a
conservative several-fold allowance for 18 assignment trajectories, manifests,
and the later audit records, the 7.3 GiB NAS1 headroom is comfortably larger
than this small Dev3 block. A live usage check will be repeated after launch.

## Gates and current state

Provider-free compute-node path validation was submitted as Slurm job
`10437661`; its bounded narrow validation receipt is job `10437704`, checking
all three frozen input roots, assignment/config identity, paraphrase
compatibility, home write/read access, and the new output-root invariant. The
single home-backed smoke and frozen Dev3 launch are recorded below.

## Runtime-path follow-up (2026-09-14)

The first home-output smoke (`10437723`) still used the NAS8 Python environment
and failed before a model turn with `CodexProviderHealthError`/
`TransportClosedError`; it produced no scientific request. A provider-free exact
`CodexSdkSessionDriver` startup probe using the home-backed project environment
(`/home/aydanh/repos/rubric_gen/.venv`, `openai_codex 0.147.0`) completed on
compute job `10438158` and resolved its bundled CLI from that home-backed
environment. The clean runner and the single smoke wrapper are now operationally
pointed at that compatible home environment; no scientific source, prompt,
model, input, or identity changed.

The bounded home-vs-NAS8 dependency comparison was briefly delayed by a Slurm
controller connection failure, then completed as job `10438204` at 08:20 EDT.
It found identical key package versions in both environments, including
`openai_codex 0.147.0`, `numpy 2.2.6`, `pandas 2.3.3`, `pydantic 2.13.4`,
`websockets 16.1.1`, and `httpx 0.28.1`. The focused provider-free runtime
tests under the home environment completed as job `10438213` at 08:21 EDT
(`32 passed in 3.75s`). These are execution checks only; no provider call or
Dev3 assignment was made by either job. The next gate is one real home-backed
worker smoke with durable output under this NAS1 root, followed by the frozen
18-assignment Dev3 only if that smoke reaches a real model turn and persists its
output.

## Frozen Dev3 launch (2026-09-14 08:25 EDT)

The single real home-backed worker smoke (`10438256`) reached a real
`gpt-5.6-luna` turn and persisted `route-ok` plus its trace under
`/home/aydanh/runs/trace-task-paraphrase-required-20260914/route-smoke-10438256/`.
The frozen Dev3 runner was then submitted once as Slurm job `10438266` from
executing commit `4283f4b` (candidate identity
`attack_defense_v2.1_task_paraphrase_required`; scientific source lineage
remains the previously frozen candidate). At the first status check it was
pending for scheduler `Priority`, with no assignment started yet. It requests
the unchanged 32-CPU/512G profile and writes new durable outputs only below
`/home/aydanh/runs/trace-task-paraphrase-required-20260914/`; frozen NAS8 inputs
remain read-only. No Result10/Result20 work was launched.

## Launch recovery: historical source identity drift (2026-09-14 08:27--08:38 EDT)

Job `10438266` reached its launcher but failed before any provider/model turn or
assignment with `ValueError: pre-treatment source experiment identity mismatch`.
The candidate YAMLs declare the sealed v2.1 producer IDs
`62e39def3939`, `dddf5e1c5878`, and `e44e429b51a6`. Their historical source
YAMLs are still present, and fixed-path probe `10438315` confirmed each
completed source ledger has the corresponding declared ID and complete records;
the source YAMLs now re-derive different IDs because the shared
prompt-implementation fingerprint changed after those producers ran. No source
YAML, ledger, pretreatment rubric, or candidate output was edited.

The minimal native compatibility repair changes only
`pretreatment_reuse.source_pool`: it continues all existing payload, task,
protocol, input-byte, and completed-study checks, but anchors the producer
identity to the declared ID in the completed `study.json` receipt instead of
requiring a historical YAML to reproduce a newer prompt fingerprint. Focused
provider-free tests pass (`tests/test_pretreatment_reuse.py`: 15/15), and
compute-node config/pretreatment validation `10438337` passes for all three
candidate configs (six assignments per task). This is an execution-compatibility
fix; the candidate recipe, requests, prompts, model settings, frozen inputs and
assignment scope remain unchanged. The failed owner receipt for `10438266` is
retained; the same 18-assignment runner will be resubmitted once this fix is
committed and pushed.

The fix was committed and pushed as `47ec2ef` and the clean execution checkout
was aligned to that commit. Because `10438266` had no assignment records, the
same frozen runner was submitted once more as job `10438357`; its owner receipt
records commit `47ec2ef`, the unchanged candidate identity, and the same 18
assignment scope. At the first post-submit check it was pending for scheduler
`Priority`; no new provider call had started at that point. This retry preserves
the failed `10438266` receipt as historical evidence.

At 2026-09-14 09:18 EDT, `10438357` was actively executing the frozen
18-assignment study on `babel-n5-20`. Five assignments were complete, nine were
running, and four were pending across the three six-assignment studies; no
assignment had failed. The log showed live Full/User revision rounds and the
home-backed ledgers were receiving terminal records. NAS1/home had approximately
5.5 GiB free and 10% inode use at this checkpoint. This is an operational
progress record only; the candidate source, prompts, inputs, and assignment
scope remain unchanged.

At 10:15 EDT the preempt partition preempted `10438357` after 1:32:42. Slurm
marked the batch `PREEMPTED` and automatically requeued the same job
(`Requeue=1`, `Restarts=1`); it restarted at 10:17 EDT on `babel-u5-32`. The
home-backed study ledgers retained the 16 completed assignments and two
in-progress records throughout the transition, so the runner resumed only the
unfinished work. This is scheduler recovery, not a scientific or provider
failure.
At 12:09--12:45 EDT, provider-free compute-node probes confirmed the practical
storage distinction. NAS1 `/home/aydanh` has 15 GiB available and 4% inode use;
the candidate output tree is 1.7 GiB. The exact three da-11-1 seed manifests
are readable as metadata, but their content reads and recursive copies stall on
NAS8 (30-second `rsync` I/O timeouts and uninterruptible `dd` reads). A small
NAS1 mirror successfully copied the hash-verified local task bytes (104 MiB)
and the da-11-1 paraphrase pool; the frozen seed bytes were not rewritten or
approximated. A per-job user-namespace bind probe (`10440212`) passed, so an
exact input mirror can later be mounted at the original NAS8 paths without
changing scientific request identities once the seed records are obtainable.

The mirror attempts `10440247` (invalid `rsync --contimeout` option), `10440251`
(NAS8 task-directory timeout), `10440304` (NAS8 seed timeout), and
`10440413` (NAS8 seed timeout) are preserved as operational evidence. The
bounded content probes recovered only the rep-002 manifest (`10440463`); the
rep-001/rep-003 reads remained blocked and were stopped after their NFS I/O
became uninterruptible (`10440509`, `10440510`). No provider/model call was
made by these jobs. The frozen study remains 16/18 completed, with only
`da-11-1` Full rep-001 and rep-002 pending; no active Dev3 job is running while
the exact seed source is unreadable. NAS1 relocation is therefore the right
execution direction, but it cannot safely complete the run until the missing
 NAS8 seed content is readable or an already sealed exact copy is found.

At 12:58 EDT, the one-shot exact tar mirror `10440592` reached a compute node
with NAS1 mounted read-write but failed while enumerating the NAS8 source
(`tar: ... rep-001: Cannot savedir: Unknown error 512`). Its partial temporary
directory was removed by the provider-free compute-node cleanup probe
`10440640`; no source bytes were accepted as a seed mirror and no model call
was made. The same probe confirmed that `/home/aydanh` is `rw` on the Slurm
compute node `babel-m5-24` and that a write/remove round trip in the candidate
root succeeds. The controller view can show the parent export as read-only
while the repository submount remains writable; this is a session/mount-view
difference, so launch readiness must be checked on the compute node.

NAS1 input relocation is directionally correct and removes the NAS8 read path
for any bytes that can be copied and hash-verified. It does not solve an
unavailable source by itself: the two pending Full assignments still depend on
exact da-11-1 seed trees (including sealed elicitation and judgment records),
and those rep-001/rep-003 bytes are not yet available on a writable persistent
mirror. The study remains 16/18 complete; no scientific configuration, request
identity, or completed output changed.

## 2026-09-14 18:21 EDT — Current resume boundary

The live Slurm check has no running candidate or seed-mirror job. Historical
runner `10438266` failed before any assignment, `10438357` was preempted/cancelled
after preserving 16 completed records, and recovery attempts `10439774` and
`10440057` were cancelled while the NAS8 source was unreadable. Exact mirror
`10440592` failed during NAS8 enumeration; pending mirror submissions `10443454`
and `10443483` were cancelled before starting. None of these operations made a
new provider/model call.

The authoritative candidate study ledger remains 16/18: all six da-3-4 and
da-18-1 assignments are completed; da-11-1 has four completed assignments and
two partial Full records (`rep-001` and `rep-002`). NAS1 currently reports about
15 GiB free and 4% inode use, and the candidate tree is about 1.5 GiB. The
NAS1 mirror contains task/paraphrase bytes but `frozen-input-mirror/seed/da-11-1`
is empty; only rep-002 seed metadata was recovered. Native resume requires the
exact sealed seed contents (submission, elicitation attempt, and initial
judgment hashes), so no safe submission is possible until those bytes are
placed at a persistent NAS1 path. Reusing an older experiment's seed or
rewriting a manifest would change the frozen input identity and is prohibited.
The bounded search and minimum external artifact are documented in
`exact-seed-blocker.md` and `exact-seed-blocker.json`.
