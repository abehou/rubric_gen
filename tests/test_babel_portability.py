import copy
import json
from pathlib import Path
import shutil
import pytest
from rubric_gen.submission_revision.paraphrase_validation import (
    master_reference, valid_reference_root, validate_paraphrase_run,
)
from rubric_gen.submission_revision.experiment import load_experiment


def test_reference_origins_are_explicit_not_paths_to_open():
    assert str(master_reference('/Users/source/data','da-3-4','rubric.txt')) == '/Users/source/data/da-3-4/tests/rubric.txt'
    assert str(master_reference('.','da-3-4','rubric.txt')) == 'da-3-4/tests/rubric.txt'
    for origin in ('', 'relative/data', '/data/../other', '/data//x', '../x'):
        assert not valid_reference_root(origin)
    with pytest.raises(RuntimeError):master_reference('.', '../escape','rubric.txt')


def test_transferred_pool_relocates_without_rewriting_provenance(tmp_path):
    root=Path(__file__).resolve().parents[1]
    source=root/'runs/autonomous-dev3-20260907/isolation-readers-smoke/paraphrases'
    if not source.exists():pytest.skip('transferred local evidence not installed')
    exp=load_experiment(root/'experiments/babel/biomnibench-dev3-control-da-3-4.yaml')
    destination=tmp_path/'pool';shutil.copytree(source,destination)
    before={str(p.relative_to(destination)):p.read_bytes() for p in destination.rglob('*') if p.is_file()}
    validate_paraphrase_run(destination,exp)
    from rubric_gen.submission_revision.paraphrases import ParaphraseRunner, ParaphraseRunConfig
    def forbidden(*args):pytest.fail('historical pool must remain read-only')
    assert ParaphraseRunner(ParaphraseRunConfig(experiment=exp,output_dir=destination,max_concurrency=2),generation_operation=forbidden).run()==0
    assert before=={str(p.relative_to(destination)):p.read_bytes() for p in destination.rglob('*') if p.is_file()}
    manifest=destination/'manifest.json';data=json.loads(manifest.read_text());original=copy.deepcopy(data)
    data['tasks'][0]['master_path']='/some/unrelated/rubric.txt';manifest.write_text(json.dumps(data))
    with pytest.raises(RuntimeError,match='identity changed'):validate_paraphrase_run(destination,exp)
    manifest.write_text(json.dumps(original))
    variant=next(destination.glob('tasks/*/variant-000.txt'));variant.write_text(variant.read_text().replace('Levels:', 'WRONG:',1))
    with pytest.raises(RuntimeError):validate_paraphrase_run(destination,exp)
