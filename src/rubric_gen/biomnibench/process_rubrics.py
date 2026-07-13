#!/usr/bin/env python3
"""Generate a trajectory-informed retrospective rubric; this is not canonical."""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from textwrap import fill, indent
from typing import Any, Iterable, Protocol

from rubric_gen.biomnibench.common import PROGRESS_BAR_FORMAT, resolve_project_path
from rubric_gen.biomnibench.perturbations import (
    DEFAULT_GEMINI_API_KEY_ENV,
    DEFAULT_PERTURBER_MODEL,
    GeminiPerturber,
    extract_json_object,
    truncate,
)

try:
    from tqdm.auto import tqdm
except ImportError:  # pragma: no cover - tqdm is an optional runtime nicety.
    tqdm = None


DEFAULT_TASKS_DIR = Path("data/biomnibench-da")
DEFAULT_RUN_DIR = Path("runs/biomnibench-agents/all-gemini-20260705-185054")
OUTPUT_NAME = "process_rubric.txt"
DEFAULT_EXAMPLE_TASK_IDS = ("da-26-4", "da-19-6", "da-10-1")

LEVEL_GUIDE = """General fine-grained level meanings:
The generator chooses the number of tiers per criterion from that criterion's point value. Higher-value criteria get more distinct partial-credit tiers; lower-value criteria get fewer tiers so adjacent scores remain meaningfully separated.

- A: complete, task-specific, and explicitly evidenced in the trajectory, trace, generated artifacts, or final answer.
- B: near-complete and explicitly evidenced, with only minor omissions that do not affect the core conclusion.
- C: substantial partial work, but at least one major requirement is missing, weak, implicit, or only partly evidenced.
- D: limited partial work with major gaps, used only when the criterion has enough points to distinguish this from C and near-absence.
- E: minimal, superficial, prose-only, or too incomplete to audit, used when the criterion has enough points to distinguish this from absence.
- F: absent, wrong-task, contradicted by the trajectory, fabricated, or unsupported by any checkable evidence, used for high-value criteria with the most tiers.

Evidence-gated scoring rules:
- Award A or B only when the trajectory or artifacts show the work was actually performed; polished final prose alone is not enough.
- Use the middle or low tiers for ordinary partial credit. Do not give B for a criterion just because the final answer mentions the topic.
- When final prose conflicts with executed commands, intermediate artifacts, or trace evidence, score the executed evidence.
- Penalize unsupported specificity: invented files, columns, statistics, citations, mechanisms, or methods should push the affected criterion to the lowest applicable tier."""

NEAR_COMPLETE_B = (
    "The trajectory satisfies the central requirement of this criterion with checkable evidence, but has a minor "
    "non-core omission such as sparse documentation, one missing intermediate count, one shallow justification, "
    "or one small ambiguity that a reviewer can resolve from the surrounding artifacts."
)

MINIMAL_D = (
    "The trajectory contains only a token, superficial, or prose-only attempt at this criterion. It may name the "
    "right concept, file, method, or limitation, but it does not provide enough executed evidence or detail for a "
    "reviewer to audit the work."
)

LIMITED_PARTIAL_D = (
    "The trajectory makes a limited partial attempt with some relevant executed evidence, but major parts of this "
    "criterion are missing, implicit, or too weak to support the final conclusion."
)


@dataclass(frozen=True)
class ExistingCriterion:
    number: int
    title: str
    description: str
    levels: str


@dataclass(frozen=True)
class TaskBundle:
    task_id: str
    task_dir: Path
    instruction_path: Path
    rubric_path: Path
    trajectory_path: Path
    trace_path: Path
    answer_path: Path
    evaluation_paths: tuple[Path, ...]


@dataclass(frozen=True)
class ProcessRubricConfig:
    tasks_dir: Path = DEFAULT_TASKS_DIR
    run_dir: Path = DEFAULT_RUN_DIR
    model: str = DEFAULT_PERTURBER_MODEL
    api_key_env: str = DEFAULT_GEMINI_API_KEY_ENV
    max_input_chars: int = 140_000
    max_retries: int = 2
    max_concurrency: int = 1
    resume: bool = False
    example_task_ids: tuple[str, ...] = DEFAULT_EXAMPLE_TASK_IDS
    expected_tasks: int = 45

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "ProcessRubricConfig":
        return cls(
            tasks_dir=resolve_project_path(args.tasks_dir),
            run_dir=resolve_project_path(args.run_dir),
            model=getattr(args, "model", DEFAULT_PERTURBER_MODEL),
            api_key_env=getattr(args, "api_key_env", DEFAULT_GEMINI_API_KEY_ENV),
            max_input_chars=max(10_000, getattr(args, "max_input_chars", 140_000)),
            max_retries=max(0, getattr(args, "max_retries", 2)),
            max_concurrency=max(1, getattr(args, "max_concurrency", 1)),
            resume=getattr(args, "resume", False),
        )


@dataclass(frozen=True)
class ProcessRubricRequest:
    task_id: str
    example_process_rubrics_txt: str
    instruction_md: str
    original_rubric_txt: str
    deterministic_draft_txt: str
    trajectory_evidence_txt: str
    trace_md: str
    answer_txt: str
    previous_errors: tuple[str, ...] = ()


class ProcessRubricRewriter(Protocol):
    def rewrite(self, request: ProcessRubricRequest) -> str:
        ...


class ProcessRubricRewriteError(ValueError):
    def __init__(self, message: str, *, raw_response: str | None = None) -> None:
        super().__init__(message)
        self.raw_response = raw_response


class GeminiProcessRubricRewriter:
    def __init__(
        self,
        *,
        model: str = DEFAULT_PERTURBER_MODEL,
        api_key_env: str = DEFAULT_GEMINI_API_KEY_ENV,
    ) -> None:
        self.client = GeminiPerturber(model=model, api_key_env=api_key_env)

    def rewrite(self, request: ProcessRubricRequest) -> str:
        response = self.client.generate_content(self.build_prompt(request))
        try:
            payload = json.loads(extract_json_object(response))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ProcessRubricRewriteError(str(exc), raw_response=response) from exc
        rubric = payload.get("process_rubric_txt")
        if not isinstance(rubric, str) or not rubric.strip():
            raise ProcessRubricRewriteError("LLM response missing non-empty process_rubric_txt", raw_response=response)
        return rubric.rstrip() + "\n"

    def build_prompt(self, request: ProcessRubricRequest) -> str:
        retry_context = ""
        if request.previous_errors:
            retry_context = "\nPrevious invalid rewrite attempt(s):\n" + "\n".join(
                f"- {error}" for error in request.previous_errors
            )
        return f"""You are rewriting a BiomniBench-DA process-level grading rubric.

Return strict JSON only:
{{"process_rubric_txt": "..."}}

Task ID: {request.task_id}

Goal:
- Write a high-quality, task-specific process rubric for grading an agent's saved trajectory, trace, and answer.
- Use the original outcome rubric as the task-success baseline, but rewrite the rubric to evaluate process quality.
- Use the provided trajectory/trace evidence to make criteria concrete and atomic.
- Use the example process rubrics as in-context examples of the desired specificity, granularity, evidence gating, and level descriptions.
- Do not merely copy the deterministic draft. Improve it with task-specific methods, data checks, intermediate quantities, likely failure modes, and limitations.

Required output format:
- Start with exactly: PROCESS RUBRIC: {request.task_id.upper()}
- Include: Total Points: 100/100
- Use parseable criterion blocks: "Criterion N: Title", "Description:", and one "Levels:" line.
- Levels lines must be compatible with this form: Levels: A=... B=... C=... with optional additional contiguous letters.
- Each criterion must have at least A/B/C, the lowest level must be 0, values must strictly descend, and A-level values must sum to 100.
- For every letter in a Levels line, write a separate bracketed level description line, e.g. "[A]: ...", "[B]: ...", "[C]: ...".
- Do not return an outline that has only criterion titles, descriptions, and point values; each level description must be detailed enough to grade from trajectory evidence.
- Auto-decide the number of levels per criterion from its point value: fewer levels for small criteria, more levels for high-value criteria.
- Keep level descriptions concrete, atomic, and evidence-gated. A/B require executed evidence, not final prose alone.
- Do not paste long trajectory excerpts. Summarize process requirements derived from them.
- Do not mention these instructions or JSON in the rubric text.

{retry_context}

<example process_rubric.txt files>
{request.example_process_rubrics_txt}
</example process_rubric.txt files>

<instruction.md>
{request.instruction_md}
</instruction.md>

<original tests/rubric.txt>
{request.original_rubric_txt}
</original tests/rubric.txt>

<trajectory evidence summary>
{request.trajectory_evidence_txt}
</trajectory evidence summary>

<trace.md excerpt>
{request.trace_md}
</trace.md excerpt>

<answer.txt>
{request.answer_txt}
</answer.txt>

<deterministic scaffold draft to improve, not blindly copy>
{request.deterministic_draft_txt}
</deterministic scaffold draft to improve, not blindly copy>
"""


def read_text(path: Path, *, limit: int | None = None) -> str:
    text = path.read_text(errors="replace")
    if limit is not None and len(text) > limit:
        return text[:limit]
    return text


def task_sort_key(path: Path) -> tuple[int, int]:
    match = re.fullmatch(r"da-(\d+)-(\d+)", path.name)
    if match:
        return int(match.group(1)), int(match.group(2))
    return (10**9, 10**9)


def discover_bundles(tasks_dir: Path, run_dir: Path) -> list[TaskBundle]:
    bundles: list[TaskBundle] = []
    for task_dir in sorted((p for p in tasks_dir.iterdir() if p.is_dir() and p.name.startswith("da-")), key=task_sort_key):
        task_id = task_dir.name
        eval_dir = run_dir / "judges" / "trace" / task_id
        eval_paths = tuple(sorted(eval_dir.glob("**/evaluation.json"))) if eval_dir.is_dir() else ()
        bundles.append(
            TaskBundle(
                task_id=task_id,
                task_dir=task_dir,
                instruction_path=task_dir / "instruction.md",
                rubric_path=task_dir / "tests" / "rubric.txt",
                trajectory_path=run_dir / "tasks" / task_id / "trajectory.stream.jsonl",
                trace_path=run_dir / "workspaces" / task_id / "trace.md",
                answer_path=run_dir / "workspaces" / task_id / "answer.txt",
                evaluation_paths=eval_paths,
            )
        )
    return bundles


def validate_inputs(bundles: Iterable[TaskBundle]) -> list[str]:
    missing: list[str] = []
    for bundle in bundles:
        for label, path in (
            ("instruction", bundle.instruction_path),
            ("rubric", bundle.rubric_path),
            ("trajectory", bundle.trajectory_path),
            ("trace", bundle.trace_path),
            ("answer", bundle.answer_path),
        ):
            if not path.is_file():
                missing.append(f"{bundle.task_id}: missing {label}: {path}")
    return missing


def extract_section(text: str, heading: str, next_headings: tuple[str, ...]) -> str:
    start = re.search(rf"^##\s+{re.escape(heading)}\s*$", text, flags=re.MULTILINE)
    if not start:
        return ""
    body_start = start.end()
    end_positions = []
    for next_heading in next_headings:
        found = re.search(rf"^##\s+{re.escape(next_heading)}\s*$", text[body_start:], flags=re.MULTILINE)
        if found:
            end_positions.append(body_start + found.start())
    body_end = min(end_positions) if end_positions else len(text)
    return text[body_start:body_end].strip()


def extract_question(instruction: str) -> str:
    question = extract_section(
        instruction,
        "Question",
        ("Data Files", "Required Outputs", "Environment", "Data Sources"),
    )
    return " ".join(question.split()) if question else "the task-specific biomedical data-analysis question"


def extract_data_hints(instruction: str, limit: int = 12) -> list[str]:
    data_files = extract_section(instruction, "Data Files", ("Required Outputs", "Environment", "Data Sources"))
    sources = extract_section(instruction, "Data Sources", ("Required Outputs", "Environment"))
    # Prefer the task-specific Data Files section. Many instructions include a
    # generic trace-format example whose internal "## Data Sources" heading and
    # toy `samples.csv` would otherwise look like real task data.
    combined = data_files or sources
    combined = re.sub(r"````.*?````", "", combined, flags=re.DOTALL)
    combined = re.sub(r"```.*?```", "", combined, flags=re.DOTALL)
    combined = re.split(r"\*\*Example excerpt\*\*|Example excerpt", combined, maxsplit=1)[0]
    candidates: list[str] = []
    for match in re.finditer(r"`([^`]+)`", combined):
        value = match.group(1).strip()
        if "\n" in value or len(value) > 140:
            continue
        if value and value not in candidates:
            candidates.append(value)

    def is_file_anchor(value: str) -> bool:
        return "/" in value or bool(re.search(r"\.[A-Za-z0-9]{1,8}(?:$|[}:,])", value))

    ranked = [value for value in candidates if is_file_anchor(value)]
    ranked.extend(value for value in candidates if value not in ranked)
    return ranked[:limit]


def parse_existing_criteria(rubric: str) -> list[ExistingCriterion]:
    parts = re.split(r"^Criterion\s+(\d+)\s*:\s*(.+?)\s*$", rubric, flags=re.MULTILINE)
    criteria: list[ExistingCriterion] = []
    for index in range(1, len(parts), 3):
        number = int(parts[index].strip())
        title = " ".join(parts[index + 1].split())
        body = parts[index + 2] if index + 2 < len(parts) else ""
        desc_match = re.search(r"Description:\s*(.+?)(?:\n\s*Levels:|\Z)", body, flags=re.DOTALL)
        levels_match = re.search(r"Levels:\s*([^\n]+)", body)
        description = " ".join(desc_match.group(1).split()) if desc_match else title
        levels = " ".join(levels_match.group(1).split()) if levels_match else ""
        criteria.append(ExistingCriterion(number=number, title=title, description=description, levels=levels))
    return criteria


def summarize_outcome_baseline(criteria: list[ExistingCriterion], limit: int = 8) -> str:
    if not criteria:
        return "No structured existing criteria were parsed; use the original rubric text as the outcome baseline."
    lines = []
    for criterion in criteria[:limit]:
        desc = short_text(criterion.description, 190)
        lines.append(f"- C{criterion.number} {criterion.title}: {desc}")
    if len(criteria) > limit:
        lines.append(f"- Plus {len(criteria) - limit} additional existing outcome criterion/criteria from `rubric.txt`.")
    return "\n".join(lines)


def parse_trajectory_summary(path: Path) -> dict[str, object]:
    tool_counts: dict[str, int] = {}
    commands: list[str] = []
    files_read: list[str] = []
    files_written: list[str] = []
    errors: list[str] = []
    json_events = 0
    non_json_lines = 0
    for raw in path.read_text(errors="replace").splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            non_json_lines += 1
            continue
        json_events += 1
        if not isinstance(event, dict):
            continue
        if event.get("type") == "tool_use":
            tool = str(event.get("tool_name") or "unknown")
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
            params = event.get("parameters")
            if isinstance(params, dict):
                command = params.get("command")
                if isinstance(command, str) and command not in commands:
                    commands.append(clean_inline(command))
                file_path = params.get("file_path")
                if isinstance(file_path, str):
                    if tool in {"write_file", "edit_file"}:
                        if file_path not in files_written:
                            files_written.append(file_path)
                    else:
                        if file_path not in files_read:
                            files_read.append(file_path)
        if event.get("type") == "tool_result" and event.get("status") not in {None, "success"}:
            output = event.get("output")
            if isinstance(output, str) and output.strip():
                errors.append(clean_inline(output.strip()))
    return {
        "json_events": json_events,
        "non_json_lines": non_json_lines,
        "tool_counts": tool_counts,
        "commands": commands[:8],
        "files_read": files_read[:8],
        "files_written": files_written[:8],
        "errors": errors[:5],
    }


def parse_trace_artifacts(trace_path: Path, answer_path: Path) -> dict[str, int | bool]:
    trace = read_text(trace_path)
    answer = read_text(answer_path)
    return {
        "trace_chars": len(trace),
        "answer_chars": len(answer),
        "has_objective": "objective" in trace.lower(),
        "has_approach": "approach" in trace.lower(),
        "has_results": "results" in trace.lower(),
        "has_references": "references" in trace.lower(),
        "code_blocks": trace.count("```"),
    }


def parse_evaluation_gaps(paths: tuple[Path, ...]) -> list[str]:
    gaps: list[str] = []
    for path in paths[:3]:
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        criteria = data.get("criteria", {})
        if not isinstance(criteria, dict):
            continue
        for key, value in sorted(criteria.items()):
            if not isinstance(value, dict):
                continue
            level = str(value.get("level") or "").strip().upper()
            if level and level != "A":
                reason = short_text(str(value.get("reason") or "no reason recorded"), 180)
                gaps.append(f"{key}: level {level} ({reason})")
        if gaps:
            break
    return gaps[:6]


def clean_inline(text: str) -> str:
    return " ".join(text.replace("\n", " ").split())


def short_text(text: str, length: int) -> str:
    cleaned = clean_inline(text)
    if len(cleaned) <= length:
        return cleaned
    return cleaned[: length - 3].rstrip() + "..."


def bullet_list(values: list[str], empty: str) -> str:
    if not values:
        return f"- {empty}"
    return "\n".join(f"- `{value}`" for value in values)


def plain_bullets(values: list[str], empty: str) -> str:
    if not values:
        return f"- {empty}"
    return "\n".join(f"- {value}" for value in values)


def trajectory_evidence(summary: dict[str, object], trace_info: dict[str, int | bool], gaps: list[str]) -> str:
    tool_counts = summary["tool_counts"]
    assert isinstance(tool_counts, dict)
    top_tools = sorted(tool_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
    commands = summary["commands"]
    files_read = summary["files_read"]
    files_written = summary["files_written"]
    errors = summary["errors"]
    assert isinstance(commands, list)
    assert isinstance(files_read, list)
    assert isinstance(files_written, list)
    assert isinstance(errors, list)
    return f"""- Parsed trajectory events: {summary["json_events"]} JSON events, {summary["non_json_lines"]} non-JSON preamble/status lines.
- Tool-use profile: {", ".join(f"{name}={count}" for name, count in top_tools) if top_tools else "no tool calls parsed"}.
- Representative commands: {", ".join(f"`{cmd}`" for cmd in commands[:5]) if commands else "none captured"}.
- Representative files read: {", ".join(f"`{path}`" for path in files_read[:5]) if files_read else "none captured"}.
- Representative files written: {", ".join(f"`{path}`" for path in files_written[:5]) if files_written else "none captured"}.
- Final artifacts: trace has {trace_info["trace_chars"]} characters and answer has {trace_info["answer_chars"]} characters; trace sections detected: objective={trace_info["has_objective"]}, approach={trace_info["has_approach"]}, results={trace_info["has_results"]}, references={trace_info["has_references"]}; fenced-code markers={trace_info["code_blocks"]}.
- Recorded trajectory/tool errors: {short_text("; ".join(str(error) for error in errors), 260) if errors else "none in parsed tool-result status fields"}.
- Existing judge gaps to target: {short_text("; ".join(gaps), 360) if gaps else "no non-A criteria found in available trace evaluation files"}."""


def wrap_level(text: str, prefix: str = "      ") -> str:
    return fill(clean_inline(text), width=112, initial_indent=prefix, subsequent_indent=prefix)


def adaptive_level_values(max_points: int) -> dict[str, int]:
    """Choose a useful number of rubric tiers from the criterion point value."""
    if max_points >= 20:
        letters = "ABCDEF"
        ratios = (1.0, 0.82, 0.62, 0.38, 0.14, 0.0)
    elif max_points >= 10:
        letters = "ABCDE"
        ratios = (1.0, 0.75, 0.40, 0.12, 0.0)
    elif max_points >= 6:
        letters = "ABCD"
        ratios = (1.0, 0.67, 0.33, 0.0)
    else:
        letters = "ABC"
        ratios = (1.0, 0.50, 0.0)

    values = [max_points]
    for ratio in ratios[1:-1]:
        next_value = round(max_points * ratio)
        next_value = max(1, min(values[-1] - 1, next_value))
        values.append(next_value)
    values.append(0)
    return dict(zip(letters, values, strict=True))


def format_levels(levels: dict[str, int]) -> str:
    return " ".join(f"{letter}={value}" for letter, value in levels.items())


def render_level_block(max_points: int, complete: str, partial: str, failure: str) -> str:
    levels = adaptive_level_values(max_points)
    letters = list(levels)
    lines = [f"    Levels: {format_levels(levels)}", wrap_level("[A]: " + complete)]
    if "B" in levels:
        lines.append(wrap_level("[B]: " + NEAR_COMPLETE_B))
    if len(letters) == 3:
        lines.append(wrap_level(f"[{letters[-1]}]: " + failure))
    elif len(letters) == 4:
        lines.append(wrap_level("[C]: " + partial))
        lines.append(wrap_level(f"[{letters[-1]}]: " + failure))
    elif len(letters) == 5:
        lines.append(wrap_level("[C]: " + partial))
        lines.append(wrap_level("[D]: " + MINIMAL_D))
        lines.append(wrap_level(f"[{letters[-1]}]: " + failure))
    else:
        lines.append(wrap_level("[C]: " + partial))
        lines.append(wrap_level("[D]: " + LIMITED_PARTIAL_D))
        lines.append(wrap_level("[E]: " + MINIMAL_D))
        lines.append(wrap_level(f"[{letters[-1]}]: " + failure))
    return "\n".join(lines)


def build_rubric(bundle: TaskBundle) -> str:
    instruction = read_text(bundle.instruction_path)
    rubric = read_text(bundle.rubric_path)
    question = extract_question(instruction)
    data_hints = extract_data_hints(instruction)
    criteria = parse_existing_criteria(rubric)
    trajectory_summary = parse_trajectory_summary(bundle.trajectory_path)
    trace_info = parse_trace_artifacts(bundle.trace_path, bundle.answer_path)
    gaps = parse_evaluation_gaps(bundle.evaluation_paths)
    baseline = summarize_outcome_baseline(criteria)
    core_requirements = short_text("; ".join(f"C{criterion.number} {criterion.title}" for criterion in criteria[:6]), 520)

    text = f"""PROCESS RUBRIC: {bundle.task_id.upper()}

# Process Rubric for {bundle.task_id.upper()}

Total Points: 100/100

Purpose: This rubric evaluates the agent's full analytical process for the task, using the saved action trajectory, trace, answer, and the original outcome rubric as evidence. It rewards agents that make correct, reproducible, task-specific analytical decisions before arriving at the final answer.

{LEVEL_GUIDE}

Task question: {question}

Task data anchors to verify in the process:
{bullet_list(data_hints, "Use the task-specific data files listed in `instruction.md`.")}

Original outcome-rubric anchors that the process must support:
{baseline}

Trajectory evidence used when rewriting this process rubric:
{trajectory_evidence(trajectory_summary, trace_info, gaps)}

CRITERIA (8):

Criterion 1: Task Understanding, Scope Control, and Input Integrity

    Description: Evaluates whether the trajectory shows that the agent correctly understood the task question, stayed within the task's allowed data scope, and established the correct comparison units, labels, identifiers, and required outputs before analysis.
{render_level_block(12, f"The trajectory explicitly grounds the analysis in the task question ({question}), reads the instruction before analysis, identifies the relevant local task data and required output files, verifies task-specific labels/identifiers/sample groups/features against the instruction or metadata, and avoids prohibited sources or unrelated files. The process documents these setup decisions in the trace so downstream computations can be audited.", "The trajectory mostly uses the right task and local files but setup is incomplete: it may rely on implicit assumptions about labels or file roles, skip one useful metadata check, only partially document required outputs, or make a minor scope mistake that does not invalidate the main analysis.", "The trajectory shows no reliable task-grounding step, uses incorrect or unrelated data, confuses key labels or identifiers, reads prohibited source material, omits required outputs, or begins analysis from assumptions that make the resulting answer non-auditable.")}

Criterion 2: Exploratory Data Inspection and Preprocessing Decisions

    Description: Evaluates whether the agent inspects the actual files and shapes before computation, handles missingness and data-quality issues deliberately, and records preprocessing choices that affect the analysis.
{render_level_block(12, "The trajectory inspects the relevant input files directly, reports dimensions or record counts, checks key columns or feature names, validates value ranges and missingness for fields used in filtering/grouping/statistics, and justifies all preprocessing choices such as filtering, normalization, joins, coordinate handling, identifier mapping, imputation, or exclusion. It preserves intermediate counts so the path from raw data to analysis-ready data is reproducible.", "The trajectory performs some real file inspection and preprocessing, but one or more checks are shallow or undocumented: dimensions are missing, a key column is assumed rather than validated, missingness handling is implicit, or intermediate row/feature counts are sparse. The omissions reduce confidence but do not fully undermine the analysis.", "The trajectory performs little or no direct data inspection, applies filters or transformations blindly, ignores obvious schema or quality issues, loses track of sample/feature counts, or preprocesses the data in a way that prevents independent reproduction.")}

Criterion 3: Core Analytical Workflow Execution

    Description: Evaluates whether the trajectory executes the task-specific analytical workflow needed to satisfy the original outcome rubric, not merely a superficial or final-answer-only analysis.
{render_level_block(23, f"The trajectory implements a complete workflow that would support the original rubric's core requirements. In particular, it operationalizes the existing outcome criteria such as: {core_requirements}. The workflow uses appropriate computational tools or scripts, maintains correct grouping/comparison logic, and produces the task-specific statistics, tables, models, overlaps, rankings, or plots needed for the final claim.", "The trajectory implements the main analysis idea but omits or weakens one important workflow component from the original rubric, such as an expected comparison group, normalization/statistical step, replicate-aware operation, validation pass, or secondary analysis. The result is partially informative but not a full process-level solution.", "The trajectory does not execute a valid task-specific workflow: it relies on qualitative reasoning alone, computes the wrong comparison, uses the wrong modality or feature set, substitutes unrelated summary statistics for the requested analysis, or cannot connect its computations to the original rubric requirements.")}

Criterion 4: Quantitative Evidence, Intermediate Checks, and Robustness

    Description: Evaluates whether the process produces enough quantitative evidence and sanity checks to support the final answer and detect analytical mistakes.
{render_level_block(13, "The trajectory reports concrete intermediate and final numbers at each meaningful step, including counts before and after filtering, group sizes, summary statistics, model/test outputs, threshold-dependent results, or agreement/overlap metrics as appropriate for the task. It performs sanity checks or sensitivity checks that address likely failure modes visible in this trajectory and in the original rubric, and it reconciles any surprising results before finalizing the answer.", "The trajectory reports some quantitative evidence but is thin in at least one place: few intermediate counts, limited sensitivity checks, unclear decision thresholds, or weak reconciliation of surprising values. The final answer has numerical support, but a reviewer must infer part of the reasoning chain.", "The trajectory provides little usable quantitative evidence, omits intermediate checks, reports unsupported or internally inconsistent numbers, or treats a single unvalidated output as sufficient for the final conclusion.")}

Criterion 5: Reproducibility, Code/Command Quality, and Trace Completeness

    Description: Evaluates whether the process leaves a clear, reproducible record of what code and commands were run and how outputs were produced.
{render_level_block(10, "The trajectory and trace include the actual commands, scripts, or code snippets needed to reproduce non-trivial operations; identify where generated artifacts were written; distinguish exploratory from final computations; and keep the final `trace.md` and `answer.txt` consistent with the executed workflow. The process avoids unverifiable paraphrases for important transformations.", "The trajectory contains executable work and the trace describes it, but reproducibility is incomplete: some code is summarized instead of shown, commands are missing, generated files are not clearly tied to results, or the answer and trace diverge slightly.", "The trajectory does not provide a reproducible analysis record, omits code for important computations, leaves final files empty or inconsistent, or presents results that cannot be traced back to commands or scripts.")}

Criterion 6: Final Synthesis, Interpretation, and Limitations

    Description: Evaluates whether the final answer is synthesized from the process evidence, interprets the result in the relevant biomedical/statistical context, and states limitations without overclaiming.
{render_level_block(10, "The final answer directly answers the task question, cites the key numerical evidence generated in the trajectory, aligns with the original rubric's expected interpretation, and states task-specific limitations such as sample size, missing modalities, threshold dependence, measurement noise, annotation limits, or correlation-versus-causation constraints. Biological or clinical interpretation is specific to the task and proportional to the evidence.", "The final answer is directionally responsive but synthesis is incomplete: it may cite only one quantitative result, give generic biological context, understate uncertainty, or omit a relevant limitation while still remaining broadly consistent with the executed analysis.", "The final answer does not answer the question, contradicts the trajectory's computed evidence, offers unsupported mechanistic claims, ignores important uncertainty, or fails to connect the process to the conclusion.")}

Criterion 7: Process Discipline, Error Recovery, and Iterative Refinement

    Description: Evaluates whether the trajectory shows disciplined agent behavior: planning, checking, recovering from tool/data issues, and updating the answer only after evidence supports it.
{render_level_block(10, "The trajectory shows a coherent analysis loop: read instructions, plan the workflow, inspect data, run focused scripts/commands, respond to tool errors or unexpected outputs by debugging rather than guessing, update provisional conclusions as evidence improves, and verify that required final files exist and are non-empty. Any retry or failed attempt is used to improve the final process rather than leaving stale artifacts or contradictions.", "The trajectory is mostly disciplined but has some inefficiency or weak recovery: repeated commands without clear purpose, minor stale files, a provisional answer written too early and only partly updated, or tool errors handled without fully documenting the fix. The final process remains usable.", "The trajectory is disorganized or brittle: it ignores errors, fabricates progress, repeatedly runs irrelevant commands, leaves failed analyses in place, stops before verification, or lets early mistaken assumptions dominate the final answer.")}

Criterion 8: Source Reliability and Hallucination Control

    Description: Evaluates whether all process claims, identifiers, methods, values, and biological interpretations are grounded in the provided data, executed code, or identifiable references.
{render_level_block(10, "Numerical values are traceable to provided files or documented transformations; identifiers and biological entities come from task data or named databases/references; method names match the actual code or commands run; and any outside biological claims are supported by real, checkable citations when the instruction permits references. The process explicitly avoids inventing statistics, citations, gene/protein names, or undocumented files.", "Most claims are grounded, but some interpretive statements lack citation, a few identifiers or methods are asserted from memory, or the trace does not clearly separate computed results from background knowledge. No major fabricated result is present.", "The trajectory or final artifacts include fabricated numbers, invented citations, unsupported biological mechanisms, mismatched method descriptions, hallucinated files/columns/identifiers, or claims that cannot be traced to the data or executed analysis.")}
"""
    return text.rstrip() + "\n"


def parse_rubric_levels(rubric_text: str) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    parts = re.split(r"^Criterion\s+(\d+)\s*:", rubric_text, flags=re.MULTILINE)
    for index in range(1, len(parts), 2):
        number = parts[index].strip()
        body = parts[index + 1] if index + 1 < len(parts) else ""
        match = re.search(r"Levels:\s*((?:[A-Z]=\d+\s*)+)", body)
        if not match:
            continue
        levels: dict[str, int] = {}
        for level_match in re.finditer(r"([A-Z])=(\d+)", match.group(1)):
            levels[level_match.group(1).upper()] = int(level_match.group(2))
        if levels:
            out[f"criterion_{number}"] = levels
    return out


def parse_rubric_bodies(rubric_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    parts = re.split(r"^Criterion\s+(\d+)\s*:", rubric_text, flags=re.MULTILINE)
    for index in range(1, len(parts), 2):
        number = parts[index].strip()
        body = parts[index + 1] if index + 1 < len(parts) else ""
        out[f"criterion_{number}"] = body
    return out


def validate_rubric_text(task_id: str, text: str, original: str) -> list[str]:
    errors: list[str] = []
    if task_id.upper() not in text:
        errors.append(f"{task_id}: missing matching task id")
    if len(text.strip()) < 3000:
        errors.append(f"{task_id}: generated rubric is unexpectedly short")
    if text.strip() == original.strip():
        errors.append(f"{task_id}: generated rubric matches original rubric")
    if "trajectory" not in text.lower() or "process" not in text.lower():
        errors.append(f"{task_id}: generated rubric lacks process/trajectory language")
    if "Evidence-gated scoring rules" not in text and "evidence-gated" not in text.lower():
        errors.append(f"{task_id}: generated rubric lacks evidence-gated scoring rules")
    parsed = parse_rubric_levels(text)
    bodies = parse_rubric_bodies(text)
    if len(parsed) < 6:
        errors.append(f"{task_id}: expected at least 6 parseable criteria, found {len(parsed)}")
        return errors
    total = sum(levels.get("A", 0) for levels in parsed.values())
    if total != 100:
        errors.append(f"{task_id}: A-level total is {total}, expected 100")
    for criterion, levels in parsed.items():
        letters = list(levels)
        expected_letters = [chr(ord("A") + index) for index in range(len(letters))]
        values = [levels[letter] for letter in letters]
        if len(letters) < 3:
            errors.append(f"{task_id}: {criterion} has fewer than 3 levels: {levels}")
        elif letters != expected_letters:
            errors.append(f"{task_id}: {criterion} levels are not contiguous from A: {levels}")
        elif values[-1] != 0:
            errors.append(f"{task_id}: {criterion} lowest level is not zero: {levels}")
        elif any(left <= right for left, right in zip(values, values[1:])):
            errors.append(f"{task_id}: {criterion} levels are not strictly descending: {levels}")
        body = bodies.get(criterion, "")
        for letter in letters:
            if not re.search(rf"^\s*\[{re.escape(letter)}\]\s*:", body, flags=re.MULTILINE):
                errors.append(f"{task_id}: {criterion} missing [{letter}] level description")
    return errors


def validate_generated(tasks_dir: Path, *, expected_tasks: int = 45) -> list[str]:
    errors: list[str] = []
    paths = sorted(tasks_dir.glob(f"da-*/tests/{OUTPUT_NAME}"), key=lambda path: task_sort_key(path.parents[1]))
    if len(paths) != expected_tasks:
        errors.append(f"expected {expected_tasks} {OUTPUT_NAME} files, found {len(paths)}")
    for path in paths:
        task_id = path.parents[1].name
        text = path.read_text(errors="replace")
        original = (path.parent / "rubric.txt").read_text(errors="replace")
        errors.extend(validate_rubric_text(task_id, text, original))
    return errors


class ProcessRubricGenerator:
    def __init__(
        self,
        config: ProcessRubricConfig,
        *,
        rewriter: ProcessRubricRewriter | None = None,
    ) -> None:
        self.config = config
        self.rewriter = rewriter or GeminiProcessRubricRewriter(
            model=config.model,
            api_key_env=config.api_key_env,
        )

    def run(self) -> int:
        bundles = discover_bundles(self.config.tasks_dir, self.config.run_dir)
        if len(bundles) != self.config.expected_tasks:
            print(f"ERROR: expected {self.config.expected_tasks} task directories, found {len(bundles)}")
            return 1

        missing = validate_inputs(bundles)
        if missing:
            print("ERROR: missing required inputs:")
            print(indent("\n".join(missing), "  "))
            return 1
        example_errors = self.validate_example_rubrics()
        if example_errors:
            print("ERROR: invalid process-rubric example(s):")
            print(indent("\n".join(example_errors), "  "))
            return 1
        rewrite_bundles = self.rewrite_bundles(bundles)

        print(f"Inventory passed for {len(bundles)} tasks.")
        print(f"Using {len(bundles) - len(rewrite_bundles)} in-context example rubric(s): {', '.join(self.example_task_ids_in_catalog(bundles))}")
        print(f"Rewriting {len(rewrite_bundles)} task rubric(s).")
        print(f"Mode: LLM rewrite with model {self.config.model}")
        print(f"Max concurrency: {self.config.max_concurrency}")

        records = self.write_all(rewrite_bundles)
        for record in records:
            print(f"{record['status']} {record['path']}")
        failures = [record for record in records if record["status"] == "failed"]
        if failures:
            print("ERROR: rubric rewrite failed for task(s):")
            for record in failures:
                print(f"  {record['task']}: {record.get('error', 'unknown error')}")
                print(f"    audit: {record['path']}")
            return 1

        errors = validate_generated(self.config.tasks_dir, expected_tasks=self.config.expected_tasks)
        if errors:
            print("ERROR: post-write validation failed:")
            print(indent("\n".join(errors), "  "))
            return 1
        print(f"Wrote and validated {len(bundles)} {OUTPUT_NAME} files.")
        return 0

    def example_task_ids_in_catalog(self, bundles: list[TaskBundle]) -> tuple[str, ...]:
        available = {bundle.task_id for bundle in bundles}
        return tuple(task_id for task_id in self.config.example_task_ids if task_id in available)

    def rewrite_bundles(self, bundles: list[TaskBundle]) -> list[TaskBundle]:
        examples = set(self.example_task_ids_in_catalog(bundles))
        return [bundle for bundle in bundles if bundle.task_id not in examples]

    def validate_example_rubrics(self) -> list[str]:
        errors: list[str] = []
        for task_id in self.config.example_task_ids:
            task_dir = self.config.tasks_dir / task_id
            process_path = task_dir / "tests" / OUTPUT_NAME
            rubric_path = task_dir / "tests" / "rubric.txt"
            if not task_dir.exists():
                continue
            if not process_path.is_file():
                errors.append(f"{task_id}: missing example {OUTPUT_NAME}")
                continue
            if not rubric_path.is_file():
                errors.append(f"{task_id}: missing original rubric.txt")
                continue
            errors.extend(validate_rubric_text(task_id, process_path.read_text(errors="replace"), rubric_path.read_text(errors="replace")))
        return errors

    def write_all(self, bundles: list[TaskBundle]) -> list[dict[str, str]]:
        with ProcessRubricProgress(total=len(bundles)) as progress:
            if self.config.max_concurrency == 1 or len(bundles) <= 1:
                records = []
                for bundle in bundles:
                    progress.record(bundle.task_id, "start")
                    records.append(self.write_one(bundle))
                    progress.record(records[-1]["task"], records[-1]["status"])
                    progress.update()
                return records

            records: list[dict[str, str] | None] = [None] * len(bundles)
            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as executor:
                futures = {}
                for index, bundle in enumerate(bundles):
                    progress.record(bundle.task_id, "submitted")
                    futures[executor.submit(self.write_one, bundle)] = (index, bundle)
                for future in as_completed(futures):
                    index, bundle = futures[future]
                    try:
                        record = future.result()
                    except Exception as exc:  # pragma: no cover - defensive fallback for unexpected worker errors.
                        record = {
                            "task": bundle.task_id,
                            "status": "failed",
                            "path": str(self.task_audit_dir(bundle)),
                            "error": str(exc),
                        }
                        self.write_failure_artifact(bundle, str(exc))
                    records[index] = record
                    progress.record(record["task"], record["status"])
                    progress.update()
            return [record for record in records if record is not None]

    def write_one(self, bundle: TaskBundle) -> dict[str, str]:
        output_path = bundle.task_dir / "tests" / OUTPUT_NAME
        print(f"start {bundle.task_id}", file=sys.stderr, flush=True)
        if self.config.resume and output_path.is_file():
            errors = validate_rubric_text(bundle.task_id, output_path.read_text(errors="replace"), read_text(bundle.rubric_path))
            if not errors and self.success_marker_path(bundle).is_file():
                return {"task": bundle.task_id, "status": "resumed", "path": str(output_path)}

        try:
            rubric = self.rewrite_with_retries(bundle)
        except Exception as exc:
            return {
                "task": bundle.task_id,
                "status": "failed",
                "path": str(self.task_audit_dir(bundle)),
                "error": str(exc),
            }
        status = "wrote-llm"
        output_path.write_text(rubric)
        self.write_success_artifact(bundle, output_path)
        return {"task": bundle.task_id, "status": status, "path": str(output_path)}

    def task_audit_dir(self, bundle: TaskBundle) -> Path:
        return self.config.run_dir / "process-rubrics" / bundle.task_id

    def success_marker_path(self, bundle: TaskBundle) -> Path:
        return self.task_audit_dir(bundle) / "success.json"

    def write_success_artifact(self, bundle: TaskBundle, output_path: Path) -> None:
        audit_dir = self.task_audit_dir(bundle)
        audit_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "task": bundle.task_id,
            "status": "wrote-llm",
            "output_path": str(output_path),
            "model": self.config.model,
        }
        self.success_marker_path(bundle).write_text(json.dumps(payload, indent=2) + "\n")

    def write_failure_artifact(self, bundle: TaskBundle, error: str) -> None:
        audit_dir = self.task_audit_dir(bundle)
        audit_dir.mkdir(parents=True, exist_ok=True)
        (audit_dir / "worker-error.txt").write_text(error.rstrip() + "\n")

    def write_attempt_artifacts(
        self,
        bundle: TaskBundle,
        attempt: int,
        request: ProcessRubricRequest,
        *,
        response_text: str | None = None,
        error: str | None = None,
    ) -> None:
        audit_dir = self.task_audit_dir(bundle)
        audit_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"attempt-{attempt:02d}"
        (audit_dir / f"{prefix}-request.json").write_text(json.dumps(asdict(request), indent=2) + "\n")
        if response_text is not None:
            (audit_dir / f"{prefix}-response.txt").write_text(response_text.rstrip() + "\n")
        if error is not None:
            (audit_dir / f"{prefix}-error.txt").write_text(error.rstrip() + "\n")

    def rewrite_with_retries(self, bundle: TaskBundle) -> str:
        errors: list[str] = []
        for attempt in range(1, self.config.max_retries + 2):
            request = self.build_request(bundle, tuple(errors))
            self.write_attempt_artifacts(bundle, attempt, request)
            try:
                rubric = self.rewriter.rewrite(request)
                self.write_attempt_artifacts(bundle, attempt, request, response_text=rubric)
                validation_errors = validate_rubric_text(bundle.task_id, rubric, read_text(bundle.rubric_path))
                if validation_errors:
                    raise ValueError("; ".join(validation_errors))
                return rubric
            except (ValueError, RuntimeError, json.JSONDecodeError, ProcessRubricRewriteError) as exc:
                raw_response = getattr(exc, "raw_response", None)
                self.write_attempt_artifacts(
                    bundle,
                    attempt,
                    request,
                    response_text=raw_response,
                    error=str(exc),
                )
                errors.append(str(exc))
                if attempt <= self.config.max_retries:
                    print(
                        f"retry {bundle.task_id} attempt {attempt}/{self.config.max_retries + 1}: {short_text(str(exc), 180)}",
                        file=sys.stderr,
                        flush=True,
                    )
        raise RuntimeError(f"Rubric rewrite failed after {self.config.max_retries + 1} attempt(s): {'; '.join(errors)}")

    def build_request(self, bundle: TaskBundle, errors: tuple[str, ...] = ()) -> ProcessRubricRequest:
        instruction = read_text(bundle.instruction_path)
        rubric = read_text(bundle.rubric_path)
        trajectory_summary = parse_trajectory_summary(bundle.trajectory_path)
        trace_info = parse_trace_artifacts(bundle.trace_path, bundle.answer_path)
        gaps = parse_evaluation_gaps(bundle.evaluation_paths)
        evidence = trajectory_evidence(trajectory_summary, trace_info, gaps)
        budget = self.config.max_input_chars
        example_budget = max(8_000, budget // 2)
        examples = self.example_process_rubrics(bundle.task_id, max_chars=example_budget)
        remaining_budget = max(10_000, budget - len(examples))
        return ProcessRubricRequest(
            task_id=bundle.task_id,
            example_process_rubrics_txt=examples,
            instruction_md=truncate(instruction, remaining_budget * 15 // 100),
            original_rubric_txt=truncate(rubric, remaining_budget * 15 // 100),
            deterministic_draft_txt=truncate(build_rubric(bundle), remaining_budget * 20 // 100),
            trajectory_evidence_txt=truncate(evidence, remaining_budget * 10 // 100),
            trace_md=truncate(read_text(bundle.trace_path), remaining_budget * 25 // 100),
            answer_txt=truncate(read_text(bundle.answer_path), remaining_budget * 15 // 100),
            previous_errors=errors,
        )

    def example_process_rubrics(self, target_task_id: str, *, max_chars: int) -> str:
        examples: list[tuple[str, str]] = []
        for task_id in self.config.example_task_ids:
            if task_id == target_task_id:
                continue
            path = self.config.tasks_dir / task_id / "tests" / OUTPUT_NAME
            if path.is_file():
                examples.append((task_id, path.read_text(errors="replace")))
        if not examples:
            return "No example process rubrics were available."

        rendered = self.render_examples(examples)
        if len(rendered) <= max_chars:
            return rendered
        first_task_id, first_text = examples[0]
        return self.render_examples([(first_task_id, truncate(first_text, max_chars))])

    def render_examples(self, examples: list[tuple[str, str]]) -> str:
        blocks = []
        for task_id, text in examples:
            blocks.append(f"### Example {task_id}\n\n{text.rstrip()}")
        return "\n\n".join(blocks)


class ProcessRubricProgress:
    def __init__(self, *, total: int) -> None:
        self.total = total
        self._bar: Any = None

    def __enter__(self) -> "ProcessRubricProgress":
        if tqdm is not None:
            self._bar = tqdm(
                total=self.total,
                desc="rewrite rubrics",
                unit="task",
                dynamic_ncols=True,
                bar_format=PROGRESS_BAR_FORMAT,
                file=sys.stderr,
            )
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._bar is not None:
            self._bar.close()

    def record(self, task: str, status: str) -> None:
        if self._bar is not None:
            self._bar.set_postfix_str(f"{task}: {status}")

    def update(self) -> None:
        if self._bar is not None:
            self._bar.update(1)
