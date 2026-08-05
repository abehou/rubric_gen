# Research limitations

- The primary outcome is a prespecified three-model binary RH judgment, not
  human ground truth. Report panel missingness and clustered uncertainty.
- The unit of inference is the task. Replicate rollouts do not turn 30 tasks
  into 90 independent samples.
- `prospective` is a joint adaptive-scoring and adaptive-feedback treatment. It
  does not identify a pure rubric effect.
- A lower raw RH rate in one cell is not evidence of a causal difference
  without the prespecified task-clustered contrast and uncertainty interval.
- Exact treatment metadata, structured feedback, and score histories are
  withheld from the primary audit, but an agent can naturally discuss feedback
  it received. Blinding is therefore strong but not absolute.
- Command outputs over 2,048 characters retain only a sealed head/tail preview,
  size, line count, and hash. Exact repeated values are referenced losslessly,
  but the middle of a truncated command output is unavailable to the auditor.
- The Codex permission profile blocks parent-workspace writes, credentials,
  web search, and command network access. It is not a container or a proof of
  host-level isolation against hostile same-user processes.
- The audit budget covers OpenAI, Claude, and Gemini through token preflight,
  maximum-output reservation for every allowed retry, and crash-conservative
  runtime accounting. It does not cap the online Codex solver, optimizer-judge,
  or rubric-proposer stages.
- Blinded human A/B packets are available for independent adjudication. Human
  labels are not automatically treated as the primary outcome.
