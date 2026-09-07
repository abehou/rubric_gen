"""Isolated storage diagnostic; never changes live study artifacts."""
from pathlib import Path
import json
import pytest
from rubric_gen.submission_revision.rubric_generation import RubricPolicy
from rubric_gen.submission_revision.rubric_generation_store import (
    load_rubric_generation, persist_rubric_generation,
)


def test_valid_crlf_assessment_reproduces_false_file_changed_error(tmp_path):
    source = Path("runs/studies/20260905-redteam-v5/biomnibench-da-factorial-r10-8ab12c898ae7/experiments/da-13-1/rep-003/luna/user-simulator-red-team-artifact")
    directory = source / "rubric-generations/generation-0004"
    generation = load_rubric_generation(source, 4)
    manifest = json.loads((directory / "manifest.json").read_text())
    files = {name: (directory / name).read_bytes().decode("utf-8")
             for name in manifest["file_sha256s"]
             if name not in {"criteria.json", "rubric.txt"}}
    name = "pairwise-assessment-active-rubric.json"
    original = files[name]
    files[name] = original.replace("\n", "\r\n")
    assert json.loads(files[name]) == json.loads(original)
    with pytest.raises(RuntimeError, match="rubric generation file changed: pairwise-assessment-active-rubric.json"):
        persist_rubric_generation(tmp_path, generation, RubricPolicy(manifest["policy"]), evolution_files=files)
    assert not (tmp_path / "rubric-generations/generation-0004").exists()
