"""Prepare the public HealthBench Hard subset without model/API calls."""
from rubric_gen.benchmarks.answer_only.dataset import main
from rubric_gen.runtime.process_environment import install_controlled_process_environment

if __name__ == "__main__":
    install_controlled_process_environment()
    main("healthbench-hard")
