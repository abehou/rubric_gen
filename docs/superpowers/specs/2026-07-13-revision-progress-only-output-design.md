# Revision Progress-Only Output

## Goal

Make `biomnibench-agent revise` display only its progress bar during a normal
run. Solver trajectory summaries and the final printed result block should not
compete with the progress display. Errors must remain visible.

## Design

- Force the persistent solver session used by `revise` into quiet mode. Raw
  trajectories continue to be written to the experiment artifacts.
- Remove the successful-run summary printed by the `revise` CLI handler.
- Keep the existing `tqdm` submission progress bar on stderr unchanged.
- Do not change output behavior for other BiomniBench commands.

## Verification

Add one focused CLI-level test that verifies a successful revision does not
write a summary to stdout. Extend the existing revision configuration test to
verify that the solver session is quiet. Run the full test suite afterward.
