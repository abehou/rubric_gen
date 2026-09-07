# Final Mac checkpoint verification — 2026-09-08

No experiment, provider probe, audit or solver dispatch was performed for this checkpoint.

- `PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_experiment_matrix.py tests/test_submission_revision.py tests/test_rubric_evolution.py tests/test_red_team.py tests/test_neutral_optimization.py tests/test_pair_difference.py tests/test_reward_seeking_profile.py investigation/static-neutral-20260907/test_chunk_cache.py`: **144 passed in 14.70s**.
- Same environment, `python -m pytest -q tests/test_paperbench.py`: **15 passed in 0.59s**.
- Read-only SHA-256 comparison against `selected-reference-wiring-20260907/historical-before.json` and `static-neutral-20260907/revise-01-launch.json`: **12,319 historical files unchanged, none missing; all 152 production files and four study YAMLs unchanged; manifest hash matches**. The existing historical integrity receipt was not overwritten.
- `git diff --check` on previously tracked edits: clean before staging. The complete staged check additionally reports whitespace in immutable archived patch files and pre-existing trailing blank lines in `evolution_stage.py` / `evolution_validation.py`; these bytes are preserved to retain launch hashes. Candidate files scanned for long provider/GitHub credential tokens and private-key headers: no hits. This is a targeted scan, not a guarantee of absence of every conceivable secret format.
- Registered the ten intended development configs in the exact inventory test; no production code or experiment configuration was changed during this final checkpoint.
- Earlier selected-reference acceptance includes all six saved judgments / 42 criterion bindings and both live checkpoint smokes; reused existing evidence rather than re-running providers. See the validated prerequisite report. No whole-suite pass is claimed; earlier broader checks had the documented sandbox socket failure and interrupted autorubric import.

Mac environment inspected without revealing credentials: Python 3.12.4; openai-codex 0.147.0; openai 2.48.0; anthropic 0.120.0; xlrd 2.0.2; openpyxl 3.1.5; numpy 2.2.6; pandas 2.3.3; scipy 1.18.0; scikit-learn 1.9.0. `uv.lock` is committed. Linux/Babel execution has not been validated here.

Raw test logs remain ephemeral under `/tmp/rubric-mac-checkpoint-tests.log` and `/tmp/rubric-mac-paperbench-tests.log`; this receipt is the durable result. Raw judgments, traces and failure archives remain in the transfer directories named in BABEL_HANDOFF.md, outside Git. The duplicate `EXPERIMENT_RUNS 2.md` is retained locally and excluded from the checkpoint.

Final file audit: no data/run directories, environment files, bytecode, logs or compressed runtime archives staged. A scan of candidate file contents for exact configured secret values found no matches without printing credentials.
