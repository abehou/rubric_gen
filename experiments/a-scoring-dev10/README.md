# A scoring Dev10: HealthBench / Luna

Status: prepared, **not launched**. Paid execution awaits user approval.

Branch: `codex/a-scoring-calibration-dev10`. Candidate [prompt-v2.txt](prompt-v2.txt)
uses the proposal's five score ranges and explicit minor/substantial/major defect
distinction. The proposal's grading text is retained verbatim, surrounded by the
existing untrusted-input and submitted-file handling instructions. The production
A prompt remains available for paired comparison; this candidate is used by the
independent pilot only.

## Scope

- HealthBench Result50, existing Luna solver answers.
- Score-only Static and Score-only RTT; ten fixed tasks × three replicates × two
  conditions = **60 final artifacts per auditor, 120 new A judgments total**.
- GPT auditor: **gpt-6-sol, high**. Claude auditor: **claude-haiku-5-5, high**.
- Only A is rerun. Reuse exact saved task/answer evidence; W/S/H/RH, revisions,
  paraphrases and pairwise audits receive no new calls or changes.
- Both auditors see the same new system prompt and `task_instruction`/`response`
  JSON only. Condition, existing scores, rubric and anticipated ordering are
  outside the judge input. Output schema stays integer score 0–100 plus explanation.
- Output allowance is 4096 tokens for both providers, raised from the matched
  old calls' 2048 to allow defect explanations and high reasoning. Maximum two
  attempts per artifact; all attempts count against provider caps.

## Fixed diagnostic tasks

| Task | Topic | Selection reason |
|---|---|---|
| result-001 | Wells DVT calculation | Calculation/factual-defect diagnostic |
| result-004 | BRCA counselling | Large Static H/A disagreement |
| result-018 | Toddler supplementation | Named example in the discussion |
| result-020 | Rheumatoid arthritis flare | Intermediate disagreement |
| result-023 | Orthopedic note from transcript | High-H agreement control |
| result-024 | Type 1 diabetes, hyperglycemia and ketones | Large disagreement, acute safety |
| result-030 | Bone pain and suspected vitamin D deficiency | Intermediate disagreement |
| result-059 | Health app water tracking | Lower old A, factual/usability diagnostic |
| result-060 | Vaccines at age four | High-H near-agreement control |
| result-092 | Review of diabetes chart note | Large disagreement, clinical documentation |

Selection uses Static discrepancy and task diversity, including agreement and
lower-A controls; RTT improvements were not used to select tasks. This is a
diagnostic subset, not a representative estimate of the full Result50. Reuse the
same ten task IDs for later conditions after validation and user approval.

## Cost and runtime estimate

Exact matched saved A usage underlies the estimate, including billed reasoning.
New prompt input overhead is estimated from English character count; projected
output is 1.5× old output plus 200 tokens per call. The range varies output from
1× plus 100 to 3× plus 400 and adds 20% upper retry headroom; it is a planning range.
No prompt-cache saving is assumed.

| Provider | Expected cost | Plausible range | Proposed enforced cap |
|---|---:|---:|---:|
| OpenAI | $0.62 | $0.46–1.25 | $6 |
| Anthropic | $0.052 | $0.039–0.104 | $1 |
| **Total** | **$0.67** | **$0.50–1.35** | **$7** |

GPT pricing retains the saved native relay's gpt-6-sol rates: $2/$10 per million
uncached input/output tokens. Claude's $0.10/$0.50 rates match the
[official pricing page](https://platform.claude.com/docs/en/about-claude/pricing)
checked on 2026-10-14. Current OpenAI pricing lists newer Sol variants; the pilot
keeps the requested existing gpt-6-sol auditor rather than changing model identity.
Provider ledger estimates are separate from a provider invoice.

Mac plan: two concurrent provider queues, six audit workers per queue, aggregate
12 calls (six OpenAI + six Anthropic), internal fanout one, no revision shards or
assignment workers. API-bound work; two CPU cores/~2 GiB combined working allowance
is sufficient as a planning estimate, not an OS reservation. Numerical threads
stay at one. Monitor CPU, RSS, free memory and pressure every 15 seconds; pause
dispatch below 10% free memory or under critical pressure. Expected elapsed time
5–15 minutes, allowing expanded reasoning and retry tails. Matched prior Claude
A calls averaged 4.06 seconds (p90 5.25); no live GPT latency probe was made.

OpenAI reuses the authorized iioA key and shared $1,000 credit ledger, reserving
the full remaining run cap before dispatch; Anthropic uses the authorized jAAA key
and an independent local ledger. Preparation reserves no money. All inputs,
raw responses, comparisons and billing evidence stay under ignored `runs/`.

## Validation and reporting

Report each auditor independently, on the same paired artifacts:

1. Native old A, current published old A and new A, with both score deltas kept
   distinct. Neither old A is overwritten.
2. W/S/H/A and W−S/S−H/H−A using the saved scores and candidate A; only A and H−A
   change in these pilot tables. Also show per-task Static/RTT changes.
3. Inspect new explanations against exact task/answer evidence: do material
   errors/omissions affect the selected score range, do reasons agree with the
   numeric score, and are useful agreement controls still credited?
4. Examine GPT/Claude disagreements and counterexamples. A lower mean or a
   desired Static/RTT ordering alone does not validate this prompt. H/A remain
   different scoring instruments even with improved A anchors.

## Local execution

These private scripts require the existing checkout's saved Result50 evidence
and shared helper `experiments/openai-credit/budget.py`. They are not public CLIs.

Provider-free preparation (already completed):

```sh
env PATH="$PWD/.venv/bin:$PATH" PYTHONPATH="$PWD/src" PYTHONNOUSERSITE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1 .venv/bin/python experiments/a-scoring-dev10/prepare.py
```

After approval, launch both provider queues concurrently with the same controlled
environment prefix above, using respectively:

```text
.venv/bin/python experiments/a-scoring-dev10/run.py --provider openai
.venv/bin/python experiments/a-scoring-dev10/run.py --provider anthropic
```

Monitor the two `status.json`, `resources.jsonl` and SQLite ledgers under
`runs/a-scoring-dev10-20261014/{openai,anthropic}/`. Resume skips valid completed A
records and retains unknown-usage reserves. After both queues complete, run
`report.py` with the controlled environment prefix. Its coverage check requires
all 120 A judgments before writing `COMPARISON.md`, `pilot-summary.json` and
`pilot-rows.json`. This does not replace the published full Result50 tables.
