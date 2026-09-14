"""Run only the rubric-score stage for the completed local candidate."""
from __future__ import annotations

import argparse
import os
from contextlib import nullcontext
from pathlib import Path

from dotenv import dotenv_values

from rubric_gen.runtime.audit_execution import AuditExecutor, audit_output_owner
from rubric_gen.runtime.capacity import policy, reservation
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.runner import RubricScoreRunner
from rubric_gen.submission_revision.evaluation.targets import load_evaluation_targets
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.source_resolution import resolve_study_sources


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--path-map", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-concurrency", type=int, default=2)
    args = parser.parse_args()
    for path in (args.experiment, args.runtime_config, args.path_map):
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise RuntimeError(f"required local input must be an absolute regular file: {path}")
    if not args.output_root.is_absolute() or args.output_root.is_symlink():
        raise RuntimeError("output root must be absolute and non-symlinked")
    if not 1 <= args.max_concurrency <= 4:
        raise ValueError("rubric-score concurrency must be between 1 and 4")

    os.environ["RUBRIC_GEN_PATH_MAP_FILE"] = str(args.path_map)
    os.environ["RUBRIC_GEN_RUNTIME_CONFIG"] = str(args.runtime_config)
    os.environ["RUBRIC_GEN_OPENAI_REASONING_EFFORT"] = "xhigh"
    if policy()["audit_studies"] != 1:
        raise RuntimeError("local audit studies must remain serialized")
    credentials = dotenv_values(ROOT / ".env.local")
    key = os.environ.get("OPENAI_API_KEY") or credentials.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("configured OPENAI_API_KEY absent")
    os.environ["OPENAI_API_KEY"] = str(key)

    experiment = load_experiment(args.experiment)
    study_dir = Path(str(experiment.dag["revise"]["output_dir"]))
    paraphrase_dir = Path(str(experiment.dag["paraphrase"]["output_dir"]))
    config = EvaluationConfig(
        experiment=experiment,
        study_dir=study_dir,
        paraphrase_dir=paraphrase_dir,
        output_dir=args.output_root / "rubric_score",
        max_concurrency=args.max_concurrency,
        resume=True,
    )
    sources = resolve_study_sources(study_dir, experiment)
    runner = RubricScoreRunner(config, load_evaluation_targets(config, sources))
    runner.preflight()
    reused = runner.prepare_resume()
    admission = nullcontext() if reused else reservation("audit")
    with audit_output_owner(args.output_root), admission, AuditExecutor(
        args.max_concurrency, tuple(experiment.outcome_audit["models"])
    ) as requests:
        result = runner.run_prepared(executor=requests)
    raise SystemExit(int(result))


if __name__ == "__main__":
    main()
