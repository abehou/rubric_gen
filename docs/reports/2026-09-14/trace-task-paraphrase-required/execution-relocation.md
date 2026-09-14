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
`10437661`; it checks all three frozen input roots, assignment/config identity,
paraphrase compatibility, home write/read access, and the new output-root
invariant. The same-route real worker smoke has not yet been rerun after this
relocation, and the frozen 18-assignment Dev3 has not been launched. The next
actions are to read the validation receipt, run exactly one home-backed worker
smoke, and submit `experiments/trace-task-paraphrase-required/run_candidate.sbatch`
only if both gates pass.
