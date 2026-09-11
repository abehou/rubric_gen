# Runtime control-plane incident

The local Codex CLI/controller process aborted with the observed allocator error
`memory allocation of 8292352 bytes failed`. This was a control-plane/tooling
failure on the login-side process, not a scientific assignment, provider
judgment, or Slurm worker failure. The independent Slurm direct-RH recovery
job **10398066** subsequently completed with exit code `0:0` in 00:26:22 and
delivered complete direct-window coverage.

No new recovery framework, scientific retry policy, model call, or audit judgment
was introduced for this incident. The response was to resume from the existing
Slurm receipts and preserve the completed outputs. The incident is retained here
so future runtime retrospectives distinguish controller memory failures from
provider failures and from valid scientific outcomes.

