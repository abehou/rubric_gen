"""Harvey criterion judge with an Anthropic prompt-cached task-output prefix.

This module is also a standalone script. The Harvey evaluator runs it with the
pinned benchmark checkout's Python environment so it can reuse Harvey's file
readers without modifying the checkout.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Callable

import anthropic


_VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "reasoning": {"type": "string"},
    },
    "required": ["verdict", "reasoning"],
    "additionalProperties": False,
}
_USAGE_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)


@dataclass(frozen=True)
class CriterionResult:
    id: str
    title: str
    verdict: str
    reasoning: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "verdict": self.verdict,
            "reasoning": self.reasoning,
        }


@dataclass(frozen=True)
class PreparedCriterion:
    index: int
    criterion: dict[str, object]
    prefix: str
    suffix: str


@dataclass(frozen=True)
class JudgeUsage:
    requests: int = 0
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: JudgeUsage) -> JudgeUsage:
        return JudgeUsage(
            requests=self.requests + other.requests,
            input_tokens=self.input_tokens + other.input_tokens,
            cache_creation_input_tokens=(
                self.cache_creation_input_tokens
                + other.cache_creation_input_tokens
            ),
            cache_read_input_tokens=(
                self.cache_read_input_tokens + other.cache_read_input_tokens
            ),
            output_tokens=self.output_tokens + other.output_tokens,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "output_tokens": self.output_tokens,
        }


def _usage(value: object) -> JudgeUsage:
    fields: dict[str, int] = {}
    for name in _USAGE_FIELDS:
        item = getattr(value, name, 0)
        fields[name] = item if type(item) is int and item >= 0 else 0
    return JudgeUsage(requests=1, **fields)


def _decode_json(candidate: str) -> object | None:
    try:
        return json.loads(candidate.strip())
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            return None


def _parse_verdict(text: str) -> tuple[str, str]:
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    candidates = [fenced.group(1), text] if fenced else [text]
    value = next(
        (
            decoded
            for candidate in candidates
            if (decoded := _decode_json(candidate)) is not None
        ),
        None,
    )
    if not isinstance(value, dict) or set(value) != {"verdict", "reasoning"}:
        raise ValueError("judge response must contain only verdict and reasoning")
    verdict, reasoning = value["verdict"], value["reasoning"]
    if verdict not in {"pass", "fail"} or type(reasoning) is not str:
        raise ValueError("judge response has an invalid verdict or reasoning")
    return verdict, reasoning


def split_cached_prompt(
    template: str,
    *,
    task_description: str,
    agent_output: str,
    criterion_title: str,
    match_criteria: str,
) -> tuple[str, str]:
    """Render the original prompt as a stable prefix and criterion suffix."""
    marker = "{criterion_title}"
    if template.count(marker) != 1:
        raise ValueError("Harvey criterion prompt must contain one title placeholder")
    prefix_template, suffix_template = template.split(marker)
    prefix = prefix_template.format(
        task_description=task_description,
        agent_output=agent_output,
    )
    suffix = criterion_title + suffix_template.format(
        match_criteria=match_criteria,
    )
    rendered = template.format(
        task_description=task_description,
        agent_output=agent_output,
        criterion_title=criterion_title,
        match_criteria=match_criteria,
    )
    if prefix + suffix != rendered:
        raise AssertionError("cached prompt split changed the Harvey judge prompt")
    return prefix, suffix


class CachedAnthropicJudge:
    """Judge one criterion while caching the shared task-output prefix."""

    def __init__(self, model: str, client: object | None = None) -> None:
        if not model.startswith("claude"):
            raise ValueError("Harvey cached judging requires an Anthropic model")
        self.model = model
        self.client = client or anthropic.Anthropic(max_retries=0)

    def evaluate(self, prefix: str, suffix: str) -> tuple[str, str, JudgeUsage]:
        total_usage = JudgeUsage()
        last_error: Exception | None = None
        for attempt in range(2):
            arguments: dict[str, object] = {
                "model": self.model,
                "max_tokens": 16_384,
                "temperature": 0.0,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prefix,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {"type": "text", "text": suffix},
                    ],
                }],
            }
            if attempt == 0:
                arguments["output_config"] = {
                    "format": {
                        "type": "json_schema",
                        "schema": _VERDICT_SCHEMA,
                    }
                }
            try:
                response = self.client.messages.create(**arguments)  # type: ignore[attr-defined]
            except anthropic.InternalServerError as exc:
                last_error = exc
                continue
            total_usage += _usage(getattr(response, "usage", None))
            if getattr(response, "stop_reason", None) == "max_tokens":
                raise ValueError("Harvey cached judge response reached max_tokens")
            text = "\n".join(
                block.text
                for block in getattr(response, "content", ())
                if getattr(block, "type", None) == "text"
            )
            try:
                verdict, reasoning = _parse_verdict(text)
            except ValueError as exc:
                last_error = exc
                continue
            return verdict, reasoning, total_usage
        raise ValueError(
            "Harvey cached judge returned no valid verdict after two attempts: "
            f"{last_error}"
        )


def _criterion_scope(
    criterion: dict[str, object], index: int
) -> tuple[tuple[str, ...], bool]:
    deliverables = criterion.get("deliverables", [])
    if not isinstance(deliverables, list) or any(
        type(item) is not str for item in deliverables
    ):
        raise ValueError(f"Harvey criterion {index} has invalid deliverables")
    options = criterion.get("evaluation_options", {})
    if not isinstance(options, dict):
        raise ValueError(f"Harvey criterion {index} has invalid evaluation_options")
    include_redlines = options.get("include_docx_redlines", False)
    if type(include_redlines) is not bool:
        raise ValueError(f"Harvey criterion {index} has invalid include_docx_redlines")
    return tuple(deliverables), include_redlines


def _prepare_criterion(
    index: int,
    criterion: dict[str, object],
    *,
    task_description: str,
    agent_output: str,
    prompt_template: str,
) -> PreparedCriterion:
    criterion_id = criterion.get("id")
    title = criterion.get("title")
    match = criterion.get("match_criteria")
    if any(
        type(value) is not str or not value.strip()
        for value in (criterion_id, title, match)
    ):
        raise ValueError(f"Harvey criterion {index} is invalid")
    prefix, suffix = split_cached_prompt(
        prompt_template,
        task_description=task_description,
        agent_output=agent_output,
        criterion_title=title,
        match_criteria=match,
    )
    return PreparedCriterion(index, criterion, prefix, suffix)


def _store_result(
    results: list[CriterionResult | None],
    prepared: PreparedCriterion,
    verdict: str,
    reasoning: str,
) -> None:
    results[prepared.index] = CriterionResult(
        id=str(prepared.criterion["id"]),
        title=str(prepared.criterion["title"]),
        verdict=verdict,
        reasoning=reasoning,
    )


def score_criteria(
    criteria: list[dict[str, object]],
    *,
    task_description: str,
    output_for: Callable[[tuple[tuple[str, ...], bool]], str],
    prompt_template: str,
    judge: CachedAnthropicJudge,
    parallel: int,
) -> tuple[list[CriterionResult], JudgeUsage]:
    """Warm each output-prefix cache, then judge remaining criteria in parallel."""
    if type(parallel) is not int or parallel < 1:
        raise ValueError("Harvey judge parallelism must be positive")
    groups: OrderedDict[
        tuple[tuple[str, ...], bool],
        list[tuple[int, dict[str, object]]],
    ] = OrderedDict()
    for index, criterion in enumerate(criteria):
        scope = _criterion_scope(criterion, index)
        groups.setdefault(scope, []).append((index, criterion))

    results: list[CriterionResult | None] = [None] * len(criteria)
    total_usage = JudgeUsage()
    remaining: list[PreparedCriterion] = []
    for scope, items in groups.items():
        agent_output = output_for(scope)
        prepared = [
            _prepare_criterion(
                index,
                criterion,
                task_description=task_description,
                agent_output=agent_output,
                prompt_template=prompt_template,
            )
            for index, criterion in items
        ]

        first = prepared[0]
        verdict, reasoning, usage = judge.evaluate(first.prefix, first.suffix)
        _store_result(results, first, verdict, reasoning)
        total_usage += usage
        remaining.extend(prepared[1:])

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {
            pool.submit(judge.evaluate, item.prefix, item.suffix): item
            for item in remaining
        }
        for future in as_completed(futures):
            prepared = futures[future]
            verdict, reasoning, usage = future.result()
            _store_result(results, prepared, verdict, reasoning)
            total_usage += usage

    if any(result is None for result in results):
        raise AssertionError("Harvey cached judge omitted a criterion result")
    return [result for result in results if result is not None], total_usage


def _task_agent_usage(metrics: dict[str, object]) -> dict[str, int | float]:
    usage: dict[str, int | float] = {}
    for name in ("input_tokens", "output_tokens", "wall_clock_seconds"):
        value = metrics.get(name, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"Harvey task-agent metric {name} is invalid")
        usage[name] = value
    return usage


@dataclass
class HarveyOutputLoader:
    output_dir: Path
    resolved: dict[str, str] | None
    read_file: Callable[..., str]
    load_all: Callable[[Path], str]
    track_changes_all: object
    track_changes_accept: object
    full_output: str | None = None

    def __call__(self, scope: tuple[tuple[str, ...], bool]) -> str:
        deliverables, include_redlines = scope
        if not deliverables or not self.resolved:
            if self.full_output is None:
                self.full_output = self.load_all(self.output_dir)
            return self.full_output
        sections = []
        track_changes = (
            self.track_changes_all
            if include_redlines
            else self.track_changes_accept
        )
        for name in deliverables:
            filename = self.resolved[name]
            path = self.output_dir / filename
            if not path.exists():
                sections.append(
                    f"## Agent Output: {name}\n(File not found: {filename})"
                )
                continue
            content = self.read_file(path, track_changes=track_changes)
            sections.append(f"## Agent Output: {name}\n{content}")
        return "\n\n".join(sections) if sections else "(No agent output found)"


def _resolve_output_files(
    criteria: list[dict[str, object]],
    output_dir: Path,
    match_deliverables: Callable[..., dict[str, str]],
) -> dict[str, str] | None:
    filenames = {
        name
        for criterion in criteria
        for name in criterion.get("deliverables", [])
    }
    if not filenames or not output_dir.is_dir():
        return None
    actual_files = [path.name for path in output_dir.rglob("*") if path.is_file()]
    return match_deliverables(
        {name: name for name in filenames},
        actual_files,
        output_dir=output_dir,
    )


def _score_payload(
    *,
    run_id: str,
    task: str,
    judge_model: str,
    results: list[CriterionResult],
    usage: JudgeUsage,
    metrics: dict[str, object],
) -> dict[str, object]:
    n_passed = sum(result.verdict == "pass" for result in results)
    n_criteria = len(results)
    all_pass = n_passed == n_criteria
    summary = (
        f"{n_passed}/{n_criteria} criteria passed."
        + (
            "  ALL-PASS."
            if all_pass
            else f"  Missed {n_criteria - n_passed} — task FAIL."
        )
    )
    return {
        "score": 1.0 if all_pass else 0.0,
        "max_score": 1.0,
        "summary": summary,
        "all_pass": all_pass,
        "n_criteria": n_criteria,
        "n_passed": n_passed,
        "criteria_results": [result.as_dict() for result in results],
        "run_id": run_id,
        "task": task,
        "judge_model": judge_model,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "judge_usage": usage.as_dict(),
        "task_agent_usage": _task_agent_usage(metrics),
        "doc_coverage": {
            "documents_read": metrics.get("documents_read", 0),
            "total_documents": metrics.get("total_documents", 0),
            "documents_skipped": metrics.get("documents_skipped", 0),
            "documents_read_list": metrics.get("documents_read_list", []),
            "documents_skipped_list": metrics.get("documents_skipped_list", []),
        },
    }


def _write_scores(run_dir: Path, scores: dict[str, object]) -> None:
    pending = run_dir / ".scores.json.pending"
    pending.write_text(
        json.dumps(scores, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(pending, run_dir / "scores.json")


def run_cached_evaluation(
    run_id: str,
    task: str,
    judge_model: str,
    parallel: int,
) -> dict[str, object]:
    """Evaluate one Harvey result from a materialized runtime tree."""
    runtime = Path.cwd().resolve()
    sys.path.insert(0, str(runtime))
    from evaluation.run_eval import (  # type: ignore[import-not-found]
        RESULTS_DIR,
        _resolve_task_dir,
        validate_task_config,
    )
    from evaluation.scoring import (  # type: ignore[import-not-found]
        DocxTrackChanges,
        _load_all_output,
        _match_deliverables,
        _read_file_as_text,
    )

    task_dir = _resolve_task_dir(task)
    task_path = task_dir / "task.json"
    config = json.loads(task_path.read_text(encoding="utf-8"))
    validate_task_config(config=config, task_path=task_path)
    run_dir = RESULTS_DIR / run_id
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Harvey result does not exist: {run_dir}")
    criteria = config["criteria"]
    output_dir = run_dir / "output"

    output_for = HarveyOutputLoader(
        output_dir=output_dir,
        resolved=_resolve_output_files(criteria, output_dir, _match_deliverables),
        read_file=_read_file_as_text,
        load_all=_load_all_output,
        track_changes_all=DocxTrackChanges.ALL,
        track_changes_accept=DocxTrackChanges.ACCEPT,
    )

    template = (runtime / "evaluation" / "prompts" / "rubric_criterion.txt").read_text(
        encoding="utf-8"
    )
    results, usage = score_criteria(
        criteria,
        task_description=config["title"],
        output_for=output_for,
        prompt_template=template,
        judge=CachedAnthropicJudge(judge_model),
        parallel=parallel,
    )
    metrics_path = run_dir / "metrics.json"
    metrics = (
        json.loads(metrics_path.read_text(encoding="utf-8"))
        if metrics_path.is_file()
        else {}
    )
    scores = _score_payload(
        run_id=run_id,
        task=task,
        judge_model=judge_model,
        results=results,
        usage=usage,
        metrics=metrics,
    )
    _write_scores(run_dir, scores)
    print(scores["summary"], flush=True)
    print(
        "Judge usage: "
        f"{usage.input_tokens} uncached, "
        f"{usage.cache_creation_input_tokens} cache-write, "
        f"{usage.cache_read_input_tokens} cache-read, "
        f"{usage.output_tokens} output tokens across {usage.requests} requests",
        flush=True,
    )
    return scores


def main() -> int:
    parser = argparse.ArgumentParser(description="Score one Harvey task with prompt caching")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--judge-model", required=True)
    parser.add_argument("--parallel", type=int, required=True)
    arguments = parser.parse_args()
    run_cached_evaluation(
        arguments.run_id,
        arguments.task,
        arguments.judge_model,
        arguments.parallel,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
