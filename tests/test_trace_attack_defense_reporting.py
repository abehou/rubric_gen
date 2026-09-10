import importlib.util
from pathlib import Path
from types import SimpleNamespace
import json
from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.submission_revision.evaluation.evidence_ledger import _load_feedback
from rubric_gen.submission_revision.trace_defense_prompts import VERSION


def metrics():
    path=Path(__file__).parents[1]/'experiments/trace-attack-defense-v1/metrics.py'
    spec=importlib.util.spec_from_file_location('attack_defense_metrics',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_cluster_bootstrap_preserves_replicates_and_auditors():
    module=metrics()
    rows=[{'task':str(t),'candidate':{'RH':float(t)},'static':{'RH':0.0}}
          for t in range(20) for rep in range(3) for auditor in range(2)]
    a=module.task_cluster_difference(rows,'RH')
    b=module.task_cluster_difference(rows[::6],'RH')
    assert a==b and a['draws']==10000 and a['analysis_seed']==20260910 and a['task_count']==20


def test_decision_requires_every_arm_specific_component():
    module=metrics()
    good={k:{'mean':v,'lower_one_sided95':-1.9,'upper95_below_zero':True} for k,v in
          {'RH':-5,'W_minus_S':-1,'W_minus_A':-2,'A':0,'S':0}.items()}
    assert module.decision(good)['joint_supported_pass']
    for metric in ('RH','W_minus_S','W_minus_A'):
        values={k:dict(v) for k,v in good.items()};values[metric]['mean']+=.01
        assert not module.decision(values)['joint_point_pass']
    good['A']['lower_one_sided95']=-2
    assert not module.decision(good)['joint_supported_pass']


def test_outcome_evidence_includes_real_reminder_but_never_private_attack(tmp_path):
    feedback=tmp_path/'feedback';feedback.mkdir();(feedback/'s000.json').write_text(json.dumps({'decision':'revise','concerns':[]}))
    original=_load_feedback(feedback,'s000',tmp_path)
    assert original=={'decision':'revise','concerns':[]}
    (tmp_path/'manifest.json').write_text(json.dumps({'red_team_trace_version':VERSION,'rubric_policy':'red_team_trace'}))
    reminders=tmp_path/'trace-defense-reminders';reminders.mkdir()
    prompt='ordinary feedback\n\nvisible admitted requirement'
    turn=tmp_path/'turns/turn-001';turn.mkdir(parents=True);(turn/'prompt.txt').write_text(prompt)
    (reminders/'s000.json').write_text(json.dumps({'message_component':'visible admitted requirement','final_prompt_sha256':sha256_text(prompt)}))
    private=tmp_path/'red-team';private.mkdir();(private/'attack-record.json').write_text('PRIVATE ATTACK')
    actual=_load_feedback(feedback,'s000',tmp_path)
    assert actual['trace_method_message']=='visible admitted requirement'
    assert 'PRIVATE ATTACK' not in json.dumps(actual)
