"""Observe errors via the existing generation callback; preserve exact audit semantics."""
import json
import os
from pathlib import Path
import time

from rubric_gen.runtime.llm import generate_structured
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.targets import load_evaluation_targets
from rubric_gen.submission_revision.evaluation.runner import RubricFreeScoreRunner


def observed(model, request):
    started = time.monotonic()
    try:
        result = generate_structured(model, request)
    except Exception as error:
        message = str(error)
        for name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            value = os.environ.get(name)
            if value:
                message = message.replace(value, "[redacted]")
        print(json.dumps({"model": model, "schema": request.schema_name,
                          "error_type": type(error).__name__, "error": message,
                          "seconds": round(time.monotonic() - started, 2)}), flush=True)
        raise
    print(json.dumps({"model": model, "schema": request.schema_name,
                      "response_received": True,
                      "seconds": round(time.monotonic() - started, 2)}), flush=True)
    return result


def main():
    experiment = load_experiment(Path("experiments/preflights/biomnibench-elicitation-10.yaml"))
    root = Path(str(experiment.dag["detect"]["output_dir"]))
    assert "exact-newlines-v6b" in root.parts
    config = EvaluationConfig(
        experiment=experiment,
        study_dir=Path(str(experiment.dag["revise"]["output_dir"])),
        paraphrase_dir=Path(str(experiment.dag["paraphrase"]["output_dir"])),
        output_dir=root, max_concurrency=1, resume=True,
    )
    runner = RubricFreeScoreRunner(config, load_evaluation_targets(config),
                                  generation_operation=observed)
    runner.preflight()  # Existing internal read-only preparation; not a new CLI mode.
    manifests = runner._manifests(runner._prepared)
    # Fail before any provider call or mutation if resume would replace an identity.
    for name, stage in (("absolute", "absolute_score"), ("pairwise", "pairwise_preference")):
        assert json.loads((root / stage / "manifest.json").read_text()) == manifests[name]
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
