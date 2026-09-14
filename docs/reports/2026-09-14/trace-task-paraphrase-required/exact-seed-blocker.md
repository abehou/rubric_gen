# Exact frozen seed blocker

Recorded 2026-09-14 (EDT), after the frozen Dev3 resume reconciliation.  This is
an operational/provenance record; it does not change the scientific recipe or
any completed assignment.

## Decision

The exact frozen `da-11-1` seed trees for the two unfinished Full assignments
could not be recovered from the bounded provider-free search.  No provider or
model call was made.  The two assignments therefore remain blocked rather than
being run from an approximate or reconstructed seed.

The study has 16 valid terminal assignments and two nonterminal partial records:

| task | arm | replicate | state |
| --- | --- | ---: | --- |
| `da-11-1` | Full | 1 | partial, not terminal |
| `da-11-1` | Full | 2 | partial, not terminal |

All six `da-3-4` records, all six `da-18-1` records, `da-11-1` Full replicate
3, and all three `da-11-1` User records remain preserved and unchanged.  There
is no active candidate or seed-mirror Slurm job.

## Required identities

The candidate study is
`biomnibench-da-factorial-r10-7ad21eac3648` under
`/home/aydanh/runs/trace-task-paraphrase-required-20260914/canonical/da-11-1/`.
The frozen source root recorded by the study and assignment manifests is:

`/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/control-v21-compatible/inputs/da-11-1/seed`

The exact per-replicate seed identities are:

| replicate | required `seed_sha256` | current candidate manifest evidence |
| ---: | --- | --- |
| 1 | `3889f8ae13cc525456024580daffc4a8941509ee6fca527911d0a375c9123f31` | Full partial manifest and User terminal manifest |
| 2 | `71bbaf07b9e0e1d4de62259ecf343c54554132d26062a40b8bb7daf245da6a5e` | Full partial manifest and User terminal manifest |
| 3 | `9c45a6e016051e8ef5f4c035958997effe64a8a151fbc916ff41aa498a03293f` | Full and User terminal manifests |

The assignment manifests also require task bytes
`6235d097e21c855eeafb7c4b2ad6b60c036730b17c15aba1d943ab2c615ea1a7`,
instruction bytes
`d5f9c760f72a1a71579d808f33fb4e9cc1644248119a3535011824ad18d42b0d`, selected
rubric `031f110fc1a22e53b68bf77668e9abe5ce754491e98012bf509e8b24de195074`,
development paraphrase `13196b78b9ef4df5d54871be1c09844dd51480ac111a54f69bbdd933d1d1d31`,
and initial generation `e81779ef8698663e968e284021476961c96f5381fa2a5e849d2553ba6b709461`.
These are context checks, not substitutes for the seed trees.

For replicate 2, the only recovered seed metadata records the missing sealed
payload's internal identities: elicitation workspace
`0cf102778b3401fa5ab498064682f369edaa5e6a086c1095051bb476daba24e2`, elicitation
trajectory `8824393a6e5d1ebf6b6dbe0156bac50f5ff38aa2bf4e41f9aea5f36e193c4536`,
elicitation status `40ca640bd51e053e887f629b47d0a4d12d2dac3ba80bdde140a62b726b90f24d`,
prompt `ebd77841f57f99866d74343465566d9ae9c3fcda89062bd06eaab0cfa7de1ba0`,
initial evaluation `01130623e8a5a7382427ffd3cc72b7282914e40e37ac8f530e74d24782a6f838`,
score validation `9148adeb625b784e8b867b1619340c72c35634e191b0eaa47b1d64f5f99eb328`,
usage `68a142893a3fc8f1b7f7d4525613c03b89f7eee53cc40ca3e38854434f5d1cc0`,
judgment `e391028220230e832eccd2643158d803be687015f2647af7683ad9d8eadfb37e`,
submission trajectory `c42fc9342d5ec7bad0b271e66f4417ae20b8d4fe3c5d7a411ab3b6d47c6623aa`,
and submission workspace `b99f19f671a779c85344ec3d23389f61b773bc3eb3e9c2c74d2fef0b8e7844e2`.
The metadata is not the payload and cannot safely be used to recreate it.

## Locations checked

The search used exact IDs/hashes and existing receipts rather than filename
similarity:

1. The NAS1 mirror
   `/home/aydanh/runs/trace-task-paraphrase-required-20260914/frozen-input-mirror/`
   contains hash-verified task bytes and the da-11-1 paraphrase pool, but
   `seed/da-11-1/` is empty.  `seed-manifests/rep-001.json` and
   `rep-003.json` are zero bytes; `rep-002.json` is metadata only (3,461 bytes)
   and has no submission, elicitation, or judgment payload.
2. The current NAS1 candidate tree contains the two partial trajectories and
   checkpoint artifacts, but no sealed source `submission/`,
   `elicitation_attempt/`, or `initial_judgment/` tree.  Its checkpoint workspace
   hashes differ from the required source elicitation workspace.
3. Exact hash/ID searches over `/home/aydanh/runs` and the repository's tracked
   `runs/` trees found only the current manifests, queue3 input receipts, and the
   mirror metadata.  No complete seed payload or alternate exact copy was found.
4. Git-tracked queue3 input/reuse records identify the source manifest paths and
   all three required seed hashes but contain metadata only; Git does not carry
   the seed bytes.
5. Older local historical seed directories have different experiment IDs and
   seed hashes.  They are incompatible and were not substituted.
6. Saved compute-node probes for the original NAS8 path show metadata/content
   reads timing out or returning `OSError: [Errno 512]`; the tar mirror
   (`10440592`) failed while enumerating `rep-001`.  The bounded mirror attempts
   `10440247`, `10440251`, `10440304`, `10440413`, `10440592`, `10443454`, and
   `10443483` produced no usable exact seed.  The last two were canceled before
   starting.  No new broad NAS8 scan was launched.

## Missing bytes and native constraint

For each pending replicate, the complete exact seed-set directory is missing:

* `submission/` (workspace, trajectory and its manifest);
* `elicitation_attempt/` (run workspace, prompt, trajectory, status and
  manifest);
* `initial_judgment/` (evaluation, score validation, usage, judgment and
  manifest);
* the per-replicate `manifest.json`, plus the enclosing seed-set manifest if
  present.

`resolve_seed` validates these components and their hashes before
`run_submission_revision` can start.  The study runner does not have a safe
assignment-level bypass: changing a manifest, splicing an older seed, or
reconstructing files from the partial candidate would alter the frozen input
identity.  Replicate 3 also must remain available because native pretreatment
validation checks the complete three-replicate seed set even though it is already
terminal in the candidate study.

## Minimum artifact needed to resume

An owner with access to the sealed source must place a byte-for-byte copy of the
complete exact seed set for `da-11-1` replicates 1, 2, and 3 (including the root
manifest and every hash-referenced file) at a persistent NAS1 path.  The copy
must validate to the identities above; a merely similar historical seed is not
enough.  Once that artifact is present, the next safe operations are:

```text
# provider-free validation first
resolve/validate the copied seed set against the frozen manifests

# then native missing-only resume of the existing study
sbatch experiments/trace-task-paraphrase-required/run_candidate.sbatch
```

The native runner will retain the 16 terminal records and execute only the two
missing Full assignments after validation.  No provider call is authorized
before the exact copy passes.

## Provenance and publication

The execution-relocation report records the same boundary and all prior failed
mirror jobs.  This blocker is committed as an operational finding; the local
`origin` remains a non-bare checked-out repository that rejects ordinary pushes
(`receive.denyCurrentBranch=refuse`).  No force push or destructive remote
repair was attempted.  The blocker does not invalidate the 16 completed
assignments; it prevents only completion of the frozen 18-assignment Dev3 and
its downstream audit.
