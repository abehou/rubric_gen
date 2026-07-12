# Task-Specific Process Rubric Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compile a task-specific, trajectory-blind BiomniBench process rubric into a sealed provenance bundle and let the judge consume it with strict, authoritative score recomputation.

**Architecture:** `task_rubrics.py` owns immutable task snapshots and the canonical rubric schema. `task_rubric_compiler.py` owns offline model calls and content-addressed bundles. `rubric_scoring.py` owns signed level parsing and score validation; the existing CLI and judge runner are consumers of these interfaces.

**Tech Stack:** Python 3.11 standard library, existing `tqdm` support, existing Gemini HTTP client, unittest/pytest.

## Global Constraints

- Compiler inputs are limited to `instruction.md`, `task.toml`, `tests/rubric.txt`, and bounded metadata from `environment/data`.
- Compiler requests must never include runs, trajectories, traces, answers, scores, condition IDs, or search history.
- `rubric.json` is canonical; `process_rubric.txt` is deterministically rendered from it.
- Bundles live outside task directories and sealed bundles are never overwritten.
- Add no runtime dependency.
- Preserve signed raw scores; clamp only the optimizer-facing reward to `[0, 100]`.
- Hash or schema mismatches and malformed judge criteria fail closed.
- Keep the old trajectory-informed command, clearly labeled retrospective and non-canonical.
- Do not modify or stage unrelated worktree files.

---

## File Map

- Create `src/rubric_gen/biomnibench/task_rubrics.py`: bounded data schema, task anchors, rubric models, validation, rendering.
- Create `src/rubric_gen/biomnibench/task_rubric_compiler.py`: rewriter protocol, retries, audit artifacts, sealing, bundle verification.
- Create `src/rubric_gen/biomnibench/rubric_scoring.py`: signed rubric parser and strict score recomputation.
- Modify `src/rubric_gen/biomnibench/judges.py`: external rubric resolution and score attestation.
- Modify `src/rubric_gen/biomnibench/cli.py`: canonical compiler command and judge `--rubric-set`.
- Modify `src/rubric_gen/biomnibench/__init__.py`: intentional public exports.
- Modify `src/rubric_gen/biomnibench/process_rubrics.py`: retrospective/non-canonical wording only.
- Modify `pyproject.toml`: restrict pytest discovery to `tests/`.
- Create `tests/test_task_rubrics.py`, `tests/test_task_rubric_compiler.py`, `tests/test_rubric_scoring.py`, and `tests/test_external_rubric_judge.py`.

---

### Task 1: Deterministic, Bounded Task Snapshots

**Files:**
- Modify: `pyproject.toml`
- Create: `src/rubric_gen/biomnibench/task_rubrics.py`
- Create: `tests/test_task_rubrics.py`

**Interfaces:**
- Consumes: one BiomniBench task directory.
- Produces: `SchemaSnapshotLimits`, `DataFileSnapshot`, `TaskAnchor`, `TaskSnapshot`, `build_task_snapshot`, `canonical_json`, `sha256_text`.

- [ ] **Step 1: Restrict pytest discovery**

Add:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Write failing snapshot tests**

Create temporary tasks containing CRLF TSV, commas inside tab-separated cells, `inf`/`-inf`/`-nan`, a symlink, and an invalid UTF-8 file. Test byte-for-byte determinism, sorted paths, bounded probes, no symlink following, valid bounded JSON, and absence of runtime fields.

```python
def test_task_snapshot_is_deterministic_and_runtime_blind(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    first = build_task_snapshot(task)
    second = build_task_snapshot(task)
    assert canonical_json(first.to_dict()) == canonical_json(second.to_dict())
    assert first.snapshot_sha256 == second.snapshot_sha256
    serialized = canonical_json(first.to_dict())
    for forbidden in ("trajectory", "trace.md", "answer.txt", "runs/"):
        assert forbidden not in serialized


def test_schema_preserves_task_specific_values(tmp_path: Path) -> None:
    table = find_table(build_task_snapshot(make_task(tmp_path)), "gene_exp.diff")
    assert "log2(fold_change)" in table.columns
    assert "-inf" in canonical_json(table.to_dict())
    assert "yes" in canonical_json(table.to_dict())
```

- [ ] **Step 3: Run tests and confirm RED**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_task_rubrics.py`

Expected: import error for `task_rubrics`.

- [ ] **Step 4: Implement snapshot dataclasses and bounded probing**

```python
@dataclass(frozen=True)
class SchemaSnapshotLimits:
    max_files: int = 16
    max_entries_visited: int = 256
    max_probe_bytes: int = 65_536
    max_rows: int = 20
    max_columns: int = 32
    max_examples_per_column: int = 3
    max_string_chars: int = 120
    max_output_chars: int = 12_000


@dataclass(frozen=True)
class TaskSnapshot:
    schema_version: int
    task_id: str
    question: str
    required_outputs: tuple[str, ...]
    data_files: tuple[DataFileSnapshot, ...]
    anchors: tuple[TaskAnchor, ...]
    required_summary_anchor_ids: tuple[str, ...]
    input_hashes: tuple[tuple[str, str], ...]
    snapshot_sha256: str

    def to_dict(self) -> dict[str, object]: ...


def build_task_snapshot(
    task_dir: Path,
    limits: SchemaSnapshotLimits = SchemaSnapshotLimits(),
) -> TaskSnapshot: ...
```

Walk `environment/data` in sorted relative-path order, reject symlinks, and read at most `max_probe_bytes + 1`. Detect delimiters in fixed order `tab, comma, semicolon, pipe`; do not use `csv.Sniffer`. Preserve identifiers and special numeric strings as examples. Drop trailing examples, columns, then files to meet the output budget while keeping valid JSON and omission counts.

Emit stable anchor IDs: `task:question`, `task:required-output:<name>`, `summary:Cn`, `data:<path>`, `schema:<path>#<column>`, and generic `evidence:*` anchors for events, commands, file reads/writes, artifacts, and final claims.

- [ ] **Step 5: Verify snapshot behavior**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_task_rubrics.py -k snapshot`

Expected: all snapshot tests pass, including a real `da-19-1` check for three tables with 6, 2, and 14 columns.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/rubric_gen/biomnibench/task_rubrics.py tests/test_task_rubrics.py
git commit -m "feat: snapshot immutable BiomniBench task inputs"
```

---

### Task 2: Structured Rubric Schema, Validation, and Rendering

**Files:**
- Modify: `src/rubric_gen/biomnibench/task_rubrics.py`
- Modify: `tests/test_task_rubrics.py`

**Interfaces:**
- Consumes: strict JSON and `TaskSnapshot`.
- Produces: `RubricLevel`, `RubricCriterion`, `TaskProcessRubric`, `parse_task_process_rubric`, `validate_task_process_rubric`, `render_task_process_rubric`.

- [ ] **Step 1: Write a valid fixture and failing invariant tests**

Use two criteria: a positive `A=100 B=50 C=0` criterion and a penalty `A=0 B=-5 C=-10` criterion. Test exact-key rejection, wrong task ID, bool points, skipped IDs, duplicate/unknown anchors, uncovered summary anchors, empty evidence fields, A/max mismatch, missing zero, non-descending points, and max-point total not equal to 100.

```python
def test_penalty_criterion_is_valid(snapshot: TaskSnapshot) -> None:
    payload = valid_rubric_payload(snapshot)
    rubric = parse_task_process_rubric(json.dumps(payload))
    assert validate_task_process_rubric(rubric, snapshot) == ()
    assert rubric.criteria[-1].levels[-1].points == -10


def test_unknown_anchor_is_rejected(snapshot: TaskSnapshot) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0]["task_anchors"] = ["unknown:anchor"]
    rubric = parse_task_process_rubric(json.dumps(payload))
    assert "unknown task anchor" in " ".join(validate_task_process_rubric(rubric, snapshot))
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_task_rubrics.py -k rubric`

Expected: missing structured-rubric interfaces.

- [ ] **Step 3: Implement closed-schema models and validation**

```python
@dataclass(frozen=True)
class RubricLevel:
    label: str
    points: int
    description: str


@dataclass(frozen=True)
class RubricCriterion:
    criterion_id: str
    title: str
    description: str
    max_points: int
    task_anchors: tuple[str, ...]
    required_evidence: tuple[str, ...]
    acceptable_alternatives: tuple[str, ...]
    anti_evidence: tuple[str, ...]
    verification: tuple[str, ...]
    levels: tuple[RubricLevel, ...]


@dataclass(frozen=True)
class TaskProcessRubric:
    schema_version: int
    task_id: str
    purpose: str
    criteria: tuple[RubricCriterion, ...]
```

Reject unknown keys and type coercion. Require `C1..Cn`, contiguous `A..` levels, at least three levels, strict descending signed points, exactly one zero, A equal to `max_points`, total max points 100, non-empty unique evidence lists, only known anchors, and coverage of every required summary anchor.

- [ ] **Step 4: Implement deterministic rendering**

`render_task_process_rubric()` must emit `Criterion N`, `Description`, task anchors, evidence, alternatives, anti-evidence, verification, `Levels: A=...`, and one bracketed description per level. Identical input must render identical bytes.

- [ ] **Step 5: Run tests and commit**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_task_rubrics.py`

```bash
git add src/rubric_gen/biomnibench/task_rubrics.py tests/test_task_rubrics.py
git commit -m "feat: validate structured task process rubrics"
```

---

### Task 3: Offline Compiler and Sealed Bundle Store

**Files:**
- Create: `src/rubric_gen/biomnibench/task_rubric_compiler.py`
- Create: `tests/test_task_rubric_compiler.py`

**Interfaces:**
- Consumes: Task 1/2 snapshot and rubric functions.
- Produces: `TaskRubricCompilerConfig`, `TaskRubricRequest`, `TaskRubricRewriter`, `GeminiTaskRubricRewriter`, `TaskProcessRubricCompiler`, `ResolvedRubricBundle`, `resolve_rubric_bundle`.

- [ ] **Step 1: Write failing compiler, retry, resume, and tamper tests**

Inject a fake rewriter that returns invalid JSON once, then a valid rubric. Assert requests contain only the snapshot and previous validation errors; failures leave audit artifacts but no sealed manifest; exact resume does not call the rewriter; changed input/config does not resume; existing bundles cannot be overwritten; artifact tampering breaks resolution.

```python
def test_compiler_request_is_runtime_blind(tmp_path: Path) -> None:
    compiler, rewriter = make_compiler(tmp_path)
    assert compiler.run() == 0
    request = canonical_json(asdict(rewriter.requests[0]))
    for forbidden in ("trajectory", "trace.md", "answer.txt", "condition_id", "search_history"):
        assert forbidden not in request


def test_bundle_tampering_is_detected(tmp_path: Path) -> None:
    output = compile_fixture(tmp_path)
    bundle = resolve_rubric_bundle(output, "da-1-1")
    bundle.rendered_path.write_text("tampered")
    with pytest.raises(RubricBundleError):
        resolve_rubric_bundle(output, "da-1-1")
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_task_rubric_compiler.py`

Expected: module import fails.

- [ ] **Step 3: Implement compiler configuration and rewriter protocol**

```python
@dataclass(frozen=True)
class TaskRubricCompilerConfig:
    tasks_dir: Path
    task_ids: tuple[str, ...]
    output_dir: Path
    model: str = "gemini-3.5-flash"
    api_key_env: str = "GEMINI_API_KEY"
    max_retries: int = 2
    max_concurrency: int = 1
    resume: bool = False
    temperature: float = 0.2


@dataclass(frozen=True)
class TaskRubricRequest:
    schema_version: int
    prompt_version: str
    task_snapshot: dict[str, object]
    previous_errors: tuple[str, ...] = ()


class TaskRubricRewriter(Protocol):
    def rewrite(self, request: TaskRubricRequest) -> str: ...
```

The Gemini adapter reuses `GeminiPerturber.generate_content()`. Its prompt includes the exact JSON schema and requires useful partial-credit gradients, observable evidence, anti-evidence, verification, and valid alternatives. It supplies no trajectory-derived examples.

- [ ] **Step 4: Implement atomic bundles and strict resolution**

```python
@dataclass(frozen=True)
class ResolvedRubricBundle:
    task_id: str
    rubric_set_id: str
    rubric_id: str
    rubric_sha256: str
    rubric_json_path: Path
    rendered_path: Path
    task_manifest_path: Path


def resolve_rubric_bundle(rubric_set_dir: Path, task_id: str) -> ResolvedRubricBundle: ...
```

Write `manifest.json`, `tasks/<task>/rubric.json`, `process_rubric.txt`, task `manifest.json`, `raw_response.txt`, and per-attempt request/response/error files. Record snapshot/input/model/temperature/prompt/raw/structured/rendered hashes. Use temporary directories and atomic rename. Resolution verifies root membership, fixed paths, task-manifest hash, task ID, valid status, every file hash, and rubric ID.

- [ ] **Step 5: Run tests and commit**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_task_rubric_compiler.py`

```bash
git add src/rubric_gen/biomnibench/task_rubric_compiler.py tests/test_task_rubric_compiler.py
git commit -m "feat: seal canonical task rubric bundles"
```

---

### Task 4: Canonical Compiler CLI

**Files:**
- Modify: `src/rubric_gen/biomnibench/cli.py`
- Modify: `src/rubric_gen/biomnibench/__init__.py`
- Modify: `src/rubric_gen/biomnibench/process_rubrics.py`
- Modify: `tests/test_task_rubric_compiler.py`

**Interfaces:**
- Consumes: `TaskRubricCompilerConfig.from_namespace` and compiler `run()`.
- Produces: `task-process-rubrics` and explicit public exports.

- [ ] **Step 1: Write failing parser tests**

```python
def test_cli_requires_explicit_tasks_and_output() -> None:
    args = build_parser().parse_args([
        "task-process-rubrics", "--task", "da-19-1",
        "--output-dir", "runs/biomnibench-rubrics/pilot",
    ])
    assert args.tasks == ["da-19-1"]
    with pytest.raises(SystemExit):
        build_parser().parse_args(["task-process-rubrics", "--output-dir", "out"])
```

Also assert old command help contains `trajectory-informed retrospective` and `not canonical`.

- [ ] **Step 2: Run tests and confirm RED**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_task_rubric_compiler.py -k cli`

- [ ] **Step 3: Add CLI options and exports**

Add required repeated `--task`, required `--output-dir`, tasks-dir/model/key/retry/concurrency/resume options, `run_task_process_rubrics`, and a `main()` branch. Export only intentional public compiler/schema types; add no compatibility aliases.

- [ ] **Step 4: Run parser regressions and commit**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_task_rubric_compiler.py tests/test_biomnibench_agents.py -k "cli or process_rubric"`

```bash
git add src/rubric_gen/biomnibench/cli.py src/rubric_gen/biomnibench/__init__.py src/rubric_gen/biomnibench/process_rubrics.py tests/test_task_rubric_compiler.py
git commit -m "feat: expose canonical task rubric compiler"
```

---

### Task 5: Strict Signed Scoring

**Files:**
- Create: `src/rubric_gen/biomnibench/rubric_scoring.py`
- Create: `tests/test_rubric_scoring.py`

**Interfaces:**
- Consumes: rendered rubric, `evaluation.json`, `reward.json`.
- Produces: `JudgeScoreValidationError`, `ValidatedJudgeScore`, `parse_rubric_levels_strict`, `validate_judge_score`.

- [ ] **Step 1: Write failing signed score tests**

```python
def test_recomputation_applies_penalty_and_ignores_reported_criterion_scores() -> None:
    levels = parse_rubric_levels_strict(
        "Criterion 1: Work\nLevels: A=100 B=50 C=0\n"
        "Criterion 2: Integrity\nLevels: A=0 B=-5 C=-10\n"
    )
    result = validate_judge_score(
        rubric_levels=levels,
        evaluation={"criteria": {
            "criterion_1": {"level": "B", "score": 100},
            "criterion_2": {"level": "C", "score": 0},
        }},
        reward={"score": 50},
    )
    assert (result.raw_score, result.score) == (40, 40)
    assert result.reported_score == 50
    assert not result.score_matches_reported
```

Test duplicate criteria/levels, missing levels, exact criterion key equality, unknown/non-string selected levels, bool/float/string/out-of-range reward values, and clamp behavior below 0 and above 100.

- [ ] **Step 2: Run tests and confirm RED**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_rubric_scoring.py`

- [ ] **Step 3: Implement strict parser and validator**

```python
class JudgeScoreValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedJudgeScore:
    score: int
    raw_score: int
    reported_score: int
    score_matches_reported: bool
    selected_levels: dict[str, str]
    criterion_scores: dict[str, int]
```

Parse signed values with `[+-]?\d+`. Require a non-empty rubric, exact criteria, exact labels, reward object exactly `{"score": int}`, `type(score) is int`, and reported range 0–100. Ignore judge-supplied criterion scores. Sum selected rubric values and clamp only the authoritative reward.

- [ ] **Step 4: Run tests and commit**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_rubric_scoring.py`

```bash
git add src/rubric_gen/biomnibench/rubric_scoring.py tests/test_rubric_scoring.py
git commit -m "fix: validate and recompute rubric scores"
```

---

### Task 6: External Rubric Sets and Judge Attestation

**Files:**
- Modify: `src/rubric_gen/biomnibench/judges.py`
- Modify: `src/rubric_gen/biomnibench/cli.py`
- Create: `tests/test_external_rubric_judge.py`
- Modify: `tests/test_biomnibench_agents.py`

**Interfaces:**
- Consumes: `resolve_rubric_bundle`, strict parser, strict score validator.
- Produces: `ResolvedRubric`, `JudgeRunConfig.rubric_set`, `score_validation.json`, authoritative score records.

- [ ] **Step 1: Write failing resolver and CLI tests**

Test mutual exclusion of `--rubric-set` and explicit `--rubric`, fixed lookup by `target.task`, root/task manifest mismatch, missing task, rendered hash mismatch, dry-run verification, no fallback, and backward-compatible task-local mode.

```python
def test_external_rubric_never_falls_back(tmp_path: Path) -> None:
    runner, target = make_runner_with_missing_external_task(tmp_path)
    with pytest.raises(SystemExit):
        runner.resolve_rubric(target)
    assert (target.task_dir / "tests" / "rubric.txt").is_file()
```

- [ ] **Step 2: Write failing attestation tests**

Fake a zero-exit judge that writes valid criteria but a disagreeing scalar. Assert the recomputed score is returned and `score_validation.json` contains rubric/reward/evaluation hashes. Malformed criteria must return `status=failed`, outer `exit_code=2`, `judge_exit_code=0`, and `score=None`. Score summaries must exclude failed records.

- [ ] **Step 3: Run tests and confirm RED**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_external_rubric_judge.py`

- [ ] **Step 4: Implement configuration and resolution**

```python
@dataclass(frozen=True)
class ResolvedRubric:
    text: str
    path: Path
    rubric_sha256: str
    rubric_id: str | None
    rubric_set_id: str | None
    source: str
    manifest_path: Path | None
```

Add nullable `rubric_name` and `rubric_set` to `JudgeRunConfig` with mutual exclusion. Neither option means local `rubric.txt`; explicit `--rubric process_rubric.txt` remains legacy behavior. External lookup uses the validated target task and fixed bundle paths only.

- [ ] **Step 5: Implement authoritative validation and resume attestation**

Write `score_validation.json` with `score`, `raw_score`, `reported_score`, match flag, selected levels, criterion scores, and rubric/reward/evaluation hashes. Resume only if the attestation and all hashes still match. Preserve subprocess status as `judge_exit_code`; invalid output produces outer exit code 2 and no aggregated score.

- [ ] **Step 6: Run judge regressions and commit**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_external_rubric_judge.py tests/test_rubric_scoring.py \
  tests/test_biomnibench_agents.py
```

```bash
git add src/rubric_gen/biomnibench/judges.py src/rubric_gen/biomnibench/cli.py tests/test_external_rubric_judge.py tests/test_biomnibench_agents.py
git commit -m "feat: judge with sealed external rubric bundles"
```

---

### Task 7: End-to-End Offline Verification

**Files:**
- Modify: `tests/test_task_rubric_compiler.py`
- Modify: `tests/test_external_rubric_judge.py`

**Interfaces:**
- Consumes: all earlier public interfaces.
- Produces: a network-free compile/seal/resolve/judge regression.

- [ ] **Step 1: Write one end-to-end test**

Create a fake task, compile it with a fake rewriter, resolve its bundle, fake the judge subprocess, and assert the final record includes bundle ID, rubric hash, signed raw score, authoritative clamped score, and no runtime information in the compiler request.

- [ ] **Step 2: Run focused and full tests**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_task_rubric_compiler.py tests/test_external_rubric_judge.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q
```

Expected: pytest only collects `tests/`; all tests pass without network or credentials.

- [ ] **Step 3: Verify the real task-only boundary**

Build a real `da-19-1` snapshot without a model call and assert task ID, three data files, no `runs/` input hash, and canonical serialized data-schema metadata at most 12,000 characters. The task question, summary-rubric anchors, and hashes are outside that schema-only budget. Do not call Gemini in automated tests.

- [ ] **Step 4: Verify diffs and public help**

```bash
git diff --check
.venv/bin/python -m rubric_gen.biomnibench.cli task-process-rubrics --help
.venv/bin/python -m rubric_gen.biomnibench.cli judge --help
```

Expected: no whitespace errors; help separates canonical task-only generation from retrospective generation and documents `--rubric-set`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_task_rubric_compiler.py tests/test_external_rubric_judge.py
git commit -m "test: verify frozen rubric workflow end to end"
```

---

## Final Verification

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q
git diff --check
git status --short
```

Confirm all tests pass, compiler requests are runtime-blind, bundle hashes verify, external lookup never falls back, signed penalties affect raw scores, malformed criteria fail closed, authoritative rewards are clamped recomputations, and unrelated worktree changes remain untouched.
