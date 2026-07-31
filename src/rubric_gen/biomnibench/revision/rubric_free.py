"""Rubric-free pairwise final evaluation following arXiv:2605.12474."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rubric_gen.biomnibench.utils.progress import TerminalProgress
from rubric_gen.biomnibench.utils.serialization import write_json_atomic
from rubric_gen.malt.model_judge import STRONG_JUDGE_MODELS, generate


DIMENSIONS = (
    "completeness",
    "factual_correctness",
    "conciseness",
    "relevance",
    "scientific_validity",
    "overall",
)

SYSTEM_PROMPT = """You are an expert scientific response evaluator. You will be given a task and two responses (@response_A and @response_B). Evaluate EACH response on five dimensions from 1 (worst) to 7 (best), then give an overall holistic score.

Dimensions and anchors:

1. Completeness — covers all relevant aspects of the task.
   1: misses nearly all key aspects; 4: covers roughly half; 7: covers all relevant aspects thoroughly.

2. Factual correctness — scientific and quantitative claims are accurate and not fabricated.
   1: many false or fabricated claims (5+); 3: several errors (3–4); 5: a few minor errors (1–2); 7: no detectable factual errors.

3. Conciseness — high information density without unnecessary padding.
   1: extreme padding, repetition, or bloat; 4: some unnecessary content; 7: every sentence earns its place.

4. Relevance — stays focused on the task asked.
   1: substantially off-topic; 4: mostly on-topic with some drift; 7: entirely focused.

5. Scientific validity — methods, evidence, uncertainty, and reproducibility are appropriate for the scientific task.
   1: invalid or irreproducible approach with critical unsupported conclusions; 4: meaningful methodological or evidentiary gaps; 7: sound, well-supported, appropriately qualified, and reproducible.

Score each dimension independently for EACH response and give a brief 1–2 sentence justification. Then assign an overall holistic 1–7 score to each response; it need not average the dimensions. Give a 2–3 sentence comparative explanation. Be fair and objective and do not let response ordering bias you. Pay special attention to factual correctness: a response that lists more items but gets several wrong should score below a shorter response that is fully accurate. Do not use or infer any rubric, score, feedback, trajectory, treatment condition, or revision number.
"""


@dataclass(frozen=True)
class RubricFreeConfig:
    experiment_dirs: tuple[Path, ...]
    output_dir: Path
    models: tuple[str, ...] = STRONG_JUDGE_MODELS
    max_concurrency: int = 3
    max_retries: int = 2
    resume: bool = False

    def __post_init__(self) -> None:
        if not self.experiment_dirs:
            raise ValueError("rubric-free evaluation requires experiments")
        if len(self.models) != 3:
            raise ValueError("rubric-free evaluation requires exactly three judges")
        if self.max_concurrency < 1 or self.max_retries < 0:
            raise ValueError("invalid rubric-free concurrency or retry count")


def _parse(text: str) -> dict[str, object]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("rubric-free response contains no JSON object")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict) or set(value) != {
        "response_A", "response_B", "comparative_explanation"
    }:
        raise ValueError("rubric-free response has invalid top-level schema")
    for response in ("response_A", "response_B"):
        item = value[response]
        if not isinstance(item, dict) or set(item) != set(DIMENSIONS):
            raise ValueError("rubric-free response has invalid response schema")
        for dimension in DIMENSIONS:
            score = item[dimension]
            if (
                not isinstance(score, dict)
                or set(score) != {"score", "justification"}
                or isinstance(score["score"], bool)
                or not isinstance(score["score"], (int, float))
                or not 1 <= score["score"] <= 7
                or not isinstance(score["justification"], str)
                or not score["justification"].strip()
            ):
                raise ValueError("rubric-free dimension has invalid values")
    if not isinstance(value["comparative_explanation"], str):
        raise ValueError("rubric-free comparison explanation is invalid")
    return value


def _prompt(instruction: str, response_a: str, response_b: str) -> str:
    shape = {
        response: {
            dimension: {"score": 1, "justification": "brief evidence-based reason"}
            for dimension in DIMENSIONS
        }
        for response in ("response_A", "response_B")
    }
    shape["comparative_explanation"] = "2–3 sentence comparison"
    return f"""{SYSTEM_PROMPT}

<task>
{instruction}
</task>
<response_A>
{response_a}
</response_A>
<response_B>
{response_b}
</response_B>

Return exactly one JSON object in this shape:
{json.dumps(shape, indent=2)}
"""


class RubricFreeRunner:
    def __init__(
        self,
        config: RubricFreeConfig,
        *,
        generate_response: Callable[[str, str], str] = generate,
    ) -> None:
        self.config = config
        self.generate_response = generate_response

    def run(self) -> int:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        retained = self._completed_records() if self.config.resume else []
        retained_keys = {
            (record["experiment"], record["model"], record["flipped"])
            for record in retained
        }
        jobs = [
            (experiment, model, flipped)
            for experiment in self.config.experiment_dirs
            for model in self.config.models
            for flipped in (False, True)
            if (str(experiment), model, flipped) not in retained_keys
        ]
        records = retained
        total = len(retained) + len(jobs)
        with TerminalProgress(
            total=total,
            description="rubric-free judging",
            unit="judgment",
        ) as progress:
            for _ in retained:
                progress.update()
            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                futures = {pool.submit(self._one, *job): job for job in jobs}
                for future in as_completed(futures):
                    experiment, model, flipped = futures[future]
                    try:
                        records.append(future.result())
                    except Exception as exc:
                        records.append({
                            "experiment": str(experiment), "model": model,
                            "flipped": flipped, "status": "failed", "error": str(exc),
                        })
                    self._write_summary(records)
                    progress.update()
                    progress.set_status(
                        f"failed={sum(r['status'] == 'failed' for r in records)}"
                    )
        self._write_summary(records)
        return int(any(record["status"] == "failed" for record in records))

    def _write_summary(self, records: list[dict[str, object]]) -> None:
        records.sort(key=lambda item: (
            str(item["experiment"]), str(item["model"]), bool(item["flipped"])
        ))
        summary = self._aggregate(records)
        write_json_atomic(self.config.output_dir / "summary.json", summary)

    def _completed_records(self) -> list[dict[str, object]]:
        summary_path = self.config.output_dir / "summary.json"
        if not summary_path.is_file():
            return []
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid rubric-free resume summary: {exc}") from exc
        if (
            not isinstance(summary, dict)
            or summary.get("kind") != "rubric-free-pairwise-final-evaluation"
            or summary.get("protocol", {}).get("models") != list(self.config.models)
            or not isinstance(summary.get("records"), list)
        ):
            raise RuntimeError("rubric-free resume summary has incompatible identity")
        expected_experiments = {str(path) for path in self.config.experiment_dirs}
        retained: list[dict[str, object]] = []
        seen: set[tuple[object, object, object]] = set()
        for record in summary["records"]:
            if not isinstance(record, dict) or record.get("status") != "completed":
                continue
            key = (record.get("experiment"), record.get("model"), record.get("flipped"))
            if (
                key in seen
                or key[0] not in expected_experiments
                or key[1] not in self.config.models
                or type(key[2]) is not bool
            ):
                raise RuntimeError("rubric-free resume summary has invalid records")
            seen.add(key)
            retained.append(record)
        return retained

    def _one(self, experiment: Path, model: str, flipped: bool) -> dict[str, object]:
        manifest = json.loads((experiment / "manifest.json").read_text())
        task_dir = Path(str(manifest["task_dir"]))
        submissions = sorted((experiment / "submissions").glob("s*"))
        if len(submissions) < 2:
            raise ValueError(f"rubric-free comparison requires two submissions: {experiment}")
        initial = (submissions[0] / "workspace" / "answer.txt").read_text()
        final = (submissions[-1] / "workspace" / "answer.txt").read_text()
        instruction = (task_dir / "instruction.md").read_text()
        left, right = (final, initial) if flipped else (initial, final)
        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 2):
            try:
                verdict = _parse(self.generate_response(model, _prompt(instruction, left, right)))
                return {
                    "experiment": str(experiment), "task_id": manifest["task_id"],
                    "model": model, "flipped": flipped, "status": "completed",
                    "attempt_count": attempt, "verdict": verdict,
                }
            except Exception as exc:
                last_error = exc
        raise RuntimeError(str(last_error))

    def _aggregate(self, records: list[dict[str, object]]) -> dict[str, object]:
        experiments = {}
        for experiment in self.config.experiment_dirs:
            relevant = [r for r in records if r["experiment"] == str(experiment)]
            judges = {}
            for model in self.config.models:
                pair = [r for r in relevant if r["model"] == model and r["status"] == "completed"]
                if len(pair) != 2:
                    judges[model] = {"status": "failed"}
                    continue
                averaged = {side: {} for side in ("initial", "final")}
                for dimension in DIMENSIONS:
                    normal = next(r for r in pair if not r["flipped"])["verdict"]
                    flipped = next(r for r in pair if r["flipped"])["verdict"]
                    averaged["initial"][dimension] = (
                        normal["response_A"][dimension]["score"]
                        + flipped["response_B"][dimension]["score"]
                    ) / 2
                    averaged["final"][dimension] = (
                        normal["response_B"][dimension]["score"]
                        + flipped["response_A"][dimension]["score"]
                    ) / 2
                delta = averaged["final"]["overall"] - averaged["initial"]["overall"]
                judges[model] = {
                    "status": "completed", "scores": averaged,
                    "winner": "final" if delta > 0 else "initial" if delta < 0 else "tie",
                    "overall_delta": delta,
                }
            votes = [j["winner"] for j in judges.values() if j.get("status") == "completed"]
            majority = (
                "final" if votes.count("final") >= 2 else
                "initial" if votes.count("initial") >= 2 else "tie"
            )
            consensus = votes[0] if len(votes) == 3 and len(set(votes)) == 1 else None
            experiments[str(experiment)] = {
                "judges": judges, "majority_winner": majority,
                "consensus_winner": consensus,
            }
        return {
            "schema_version": 1,
            "kind": "rubric-free-pairwise-final-evaluation",
            "paper": "arXiv:2605.12474",
            "protocol": {
                "position_flipped": True,
                "scale": [1, 7],
                "dimensions": list(DIMENSIONS),
                "domain_adaptation": "medical safety replaced by scientific validity/reproducibility",
                "models": list(self.config.models),
            },
            "records": records,
            "experiments": experiments,
        }
