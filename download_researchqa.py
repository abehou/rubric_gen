"""Prepare ResearchQA validation Dev3 or held-out test Result20, without API calls."""
from rubric_gen.benchmarks.answer_only.dataset import main
from rubric_gen.runtime.process_environment import install_controlled_process_environment

if __name__ == "__main__":
    install_controlled_process_environment()
    main("researchqa-parametric")
