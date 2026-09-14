# Frozen Dev3 execution relocation (NAS1)

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
