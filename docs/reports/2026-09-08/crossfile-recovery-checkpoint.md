# Crossfile recovery checkpoint — 2026-09-08 23:59 EDT

The current test is incomplete: 37 original assignments completed, 22 running, and one infrastructure failure. Job 10366421 remains live. The failed da-13-3 replicate 1 revision was regenerated successfully by 10366940 using isolated source a587028; its audits are running. No successful original assignment was restarted.

Primary coverage will be 59 original cases plus the one repaired case. Survivor audit 10366975 waits for the original owner to terminate; report 10366435 depends on both that audit and repair 10366940. Guards reject additional failures rather than silently excluding them.

Optional artifact-v2 validation 10366468 is held because its existing reader assumes one complete 60-case source. Next: adapt it to original59 + repair1 with the unchanged v2 prompt and verified source-specific scope, then release/requeue validation. Dependent optional jobs10366473 and10366475 have not run. This does not block the primary comparison.

The completed preceding cue comparison showed full-trajectory RH20% static versus7.5% trace, with original final-artifact RH0% in both. Separate calibration did not establish final-artifact mitigation. Current crossfile results must also disclose regenerated starting rubrics on10/20 tasks; this is exploratory evidence, not a perfectly isolated prompt effect.

## 2026-09-09 00:10 EDT — remaining runtime tail

Read-only inspection confirmed continued progress: two more assignments completed during inspection, leaving six original revisions. Remaining saved score counts are9–10; recent writes include checkpoint8/9 sidecars, rubric-proposer records, and final submission evaluation inputs. Older state.json timestamps alone would have falsely suggested inactivity: two cases had fresh evaluation/proposer files within seconds. No new terminal failure was observed. Preserve active calls; the remaining delay is sequential late-round work, not evidence that additional CPUs or restarting would help.

## Runtime tail snapshot

At elapsed 64.3 minutes: {'completed': 57, 'failed': 1, 'pending': 180, 'running': 2}; active provider slots 2, sampled CPU 0.058 cores, provider admission wait p95 1.30s. Recorded HTTP-status failures: {}. Runtime counters include 2 failed judge attempts and 32 repeated request attempts; these are not equivalent to failed scientific assignments. Solver-turn p95 371.7s and solver-resume p95 166.3s. Hosted request timeout is600s; configured agent-turn bound7200s. Do not infer a single call duration from state.json age or reduce concurrency merely because the final tail has few remaining calls.
