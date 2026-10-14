# PaperBench foundational-control v2 mechanism smoke

## Decision

The six-assignment mechanism smoke and its unchanged Sol+Opus audit are
complete.  The source-versus-execution correction repairs the original
`self-expansion/rep-002/User` false veto, but this candidate does **not** pass
the gate for a fresh 18-assignment Dev3.  Against the exact matched static
cells, mean S and H fall in both arms and W-S widens materially.  No full Dev3
or Results20 run was launched.

## Coverage and identity

- Revision scope: replicate 2 of `self-expansion`,
  `semantic-self-consistency`, and `self-composing-policies`, with matched Full
  and User arms (6/6 assignments).
- Every assignment completed 11/11 checkpoints.  All 66 task-completion
  decisions and 66 applicable enforcement results are valid, with zero
  `contract_exhausted` results and complete blocker/reminder receipts.
- Audit scope: 98/98 rubric judgments, 18/18 absolute judgments, 12/12 pairwise
  judgments, and 48/48 direct RH judgments.  Sol and Opus each cover every
  planned cell; there are no missing models or judge failures.
- All six initial submission hashes match their static reference exactly.

## Equal-weight Sol+Opus results

These are the three prespecified replicate-2 tasks per arm, not a full Dev3
estimate.

| Condition | Arm | W | S | H | A | W-S | S-H | H-A | W-A |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Matched static | Full | 87.206 | 79.009 | 69.157 | 39.167 | 8.196 | 9.852 | 29.990 | 48.039 |
| **Foundational v2** | **Full** | **85.480** | **66.823** | **60.616** | **46.833** | **18.657** | **6.207** | **13.783** | **38.647** |
| Matched static | User | 74.821 | 69.852 | 66.666 | 42.833 | 4.969 | 3.186 | 23.832 | 31.987 |
| **Foundational v2** | **User** | **79.132** | **56.466** | **61.114** | **44.000** | **22.666** | **-4.648** | **17.114** | **35.132** |

| Candidate minus static | dW | dS | dH | dA | d(W-S) | d(S-H) | d(H-A) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Full | -1.726 | -12.186 | -8.541 | +7.667 | +10.460 | -3.645 | -16.207 |
| User | +4.312 | -13.386 | -5.551 | +1.167 | +17.698 | -7.835 | -6.718 |

The higher A scores do not offset the S/H loss.  In particular, the smaller
S-H or H-A gaps are partly produced by lower S/H rather than better preserved
generalization.

## Direct reward-hacking audit

Among six auditor votes per arm/window, Full full-trajectory has zero detected
and two abstained votes.  Every other Full window and all four User windows
have zero detected and zero abstained votes.  This is clean direct-RH evidence,
but it does not rescue the quality/generalization gate.

## Mechanism diagnosis

The intended fix worked on the motivating failure.  The old completion-control
run returned `self-expansion/rep-002/User` to `s000`; foundational v2 selected
the verified `s007` champion.  Relative to that old selected result, the
equal-weight panel improves S by 33.573, H by 37.017, and A by 18.000 points.
It nevertheless remains below exact matched static by 11.846 S and 5.670 H.

The remaining failure is broader than execution-state classification:

- All six terminal reviews still say `candidate_complete=false` after ten
  revisions.  The controller accepts connected local repairs, but the
  PaperBench task has a longer dependency/requirement frontier than the fixed
  revision budget closes.
- The next blocker changes on every turn.  A single delivered blocker can
  guide the next repair, but it is not a persistent task-completion plan and
  does not by itself protect all previously satisfied requirements.
- The clearest case is `semantic-self-consistency/Full`: fixed-original W is
  99.653 while panel S/H are 59.375/60.378.  The terminal review accepts a
  connected improvement while explicitly recording unavailable official
  data/model execution; the independent audit still finds missing exact
  prompts/data-backed usability.  The online original-rubric signal therefore
  overstates benchmark-wide completion.
- Increasing only the User concern count is not the essential repair: Full
  shows the same incomplete-task and S/H failure.  More unstructured feedback
  would increase simultaneous directions without creating durable coverage.

The next scientific revision should retain the RTT architecture and the three
User concerns, but replace the one-step blocker queue with a cumulative,
dependency-ordered completion ledger.  Unavailable external execution should
be recorded as unavailable rather than repeatedly competing with actionable
source defects.  Candidate promotion should require monotonic progress across
that ledger and preservation of previously verified workstreams, not merely a
connected local improvement plus fixed-original score.  This is a new
treatment and requires a new mechanism gate before any full Dev3.

## Authoritative artifacts

- Study: `runs/paperbench-rtt-foundational-control-local-mac/dev3/study/paperbench-code-dev-factorial-r10-ba0c5e199d00`
- Audit: `runs/paperbench-rtt-foundational-control-local-mac/dev3/audit-sol-opus/paperbench-code-dev-factorial-r10-ba0c5e199d00`
- Completion receipt: `runs/paperbench-rtt-foundational-control-local-mac/dev3/sol-opus-audit-completion.json`

