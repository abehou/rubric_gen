"""Structural factor tests. Mock verdicts do not establish feedback accuracy."""
import ast
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rubric_gen.submission_revision import user_feedback_factors as f
from rubric_gen.submission_revision import trace_defense_delivery as delivery
from rubric_gen.submission_revision.user_simulator import _feedback_request
from rubric_gen.submission_revision.trace_defense_registry import recipe, prompt_hashes
from test_user_delivery_v3 import _criterion, _generation

ARGS=dict(instruction='Return 20% and 0.05\nReport the table.\n',full_feedback_text='private expected count 160',
          current_artifact='# Table\nObserved 52\n',history_context='[]',max_concerns=3,max_output_tokens=1024)
CHECK=dict(mode='corrective',requirement='Verify the scoped public relation.',newly_admitted=True,currently_violated=True)
ROOT=Path(__file__).resolve().parents[1]

class FeedbackFactorsTests(unittest.TestCase):
    def test_legacy_literals_and_functions_unchanged(self):
        old=subprocess.check_output(['git','show','d164a9a:src/rubric_gen/submission_revision/user_simulator.py'],cwd=ROOT,text=True)
        current=(ROOT/'src/rubric_gen/submission_revision/user_simulator.py').read_text()
        for name in ('_feedback_request','_feedback_request_v3','_validate_feedback_output'):
            nodes=[next(n for n in ast.parse(s).body if isinstance(n,ast.FunctionDef) and n.name==name) for s in (old,current)]
            self.assertEqual(ast.dump(nodes[0]),ast.dump(nodes[1]))

    def test_shared_selector_matches_historical_append_bytes(self):
        import rubric_gen.submission_revision.trace_defense_delivery as mod
        oldns=dict(mod.__dict__)
        exec(subprocess.check_output(['git','show','d164a9a:src/rubric_gen/submission_revision/trace_defense_delivery.py'],cwd=ROOT,text=True),oldns)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);gen=_generation((_criterion(),));gen.red_team_trace_version='attack_defense_v2.1'
            score=root/'score.json';score.write_text('{}')
            args=dict(generation=gen,score_validation_path=score,root=root,submission_id='s000',instruction='Task',allow_generation=True)
            # One total base criterion plus one active penalty.
            validation=(None,None,None,{'criterion_1':20,'criterion_2':-5})
            with patch.object(mod,'_validate_score_record',return_value=validation):
                oldns['_validate_score_record']=mod._validate_score_record
                projected=SimpleNamespace(prompt='ordinary')
                # dataclasses.replace requires a dataclass, use native projection.
                from rubric_gen.submission_revision.feedback import ProjectedFeedback
                projected=ProjectedFeedback(score=20,payload={},prompt='ordinary')
                old=oldns['append_reminder'](projected,**args)
                original=(root/'trace-defense-reminders/s000.json').read_bytes()
                new=mod.append_reminder(projected,**args)
                self.assertEqual(old,new);self.assertEqual(original,(root/'trace-defense-reminders/s000.json').read_bytes())

    def test_numeric_eligibility(self):
        self.assertEqual(delivery.numeric_literals('160 52 0.05 20% 1e-3'),{'160','52','0.05','20%','1e-3'})
        self.assertEqual(delivery.numeric_literals('-2 +3 -.5 +.25 1,600 2E+4 -1.2e-3 0%'),{'-2','+3','-.5','+.25','1,600','2E+4','-1.2e-3','0%'})
        self.assertIs(f.select_reminder,delivery.select_reminder)

    def test_d_only_no_check_is_exact_base_request(self):
        self.assertEqual(asdict(_feedback_request(**ARGS)),asdict(f.feedback_request(trace_version='attack_defense_user_d1g0',**ARGS)))

    def test_d_only_exact_append_and_budget(self):
        base=_feedback_request(**ARGS);r=f.feedback_request(trace_version='attack_defense_user_d1g0',focused_dynamic_check=CHECK,**ARGS)
        self.assertEqual(r.instructions,base.instructions+'\n\n'+f.DELIVERY)
        self.assertEqual(r.schema,base.schema)
        self.assertNotIn('base_requirement_status',r.evidence)
        self.assertNotIn('Focused review check',r.instructions)
        self.assertIn('nonviolated proactive check alone is not a reason',r.instructions)

    def test_grounded_schema_and_no_extra_public_information(self):
        r=f.feedback_request(trace_version='attack_defense_user_d0g1',**ARGS)
        self.assertIn(f.GROUNDING,r.instructions);self.assertNotIn(f.DELIVERY,r.instructions)
        self.assertIn('private expected count 160',r.evidence)
        self.assertIn('[L000002]',r.evidence)
        self.assertEqual(r.schema['properties']['concerns']['maxItems'],3)
        self.assertEqual(r.max_output_tokens,1024)

    def test_metadata_cannot_change_decision_or_remove_concerns(self):
        raw={'decision':'revise','concerns':[{'category':'interpretation','feedback':'Verify this unresolved computation.',
             'basis':'verification_request','public_refs':[{'source_id':'artifact','start_line':1,'end_line':2}]}]}
        a=f.validate_output(raw,trace_version='attack_defense_user_d0g1',instruction=ARGS['instruction'],current_artifact=ARGS['current_artifact'],max_concerns=3)
        b=deepcopy(a);b['concerns'][0]['basis']='observed_defect'
        self.assertEqual(f.solver_feedback(a),f.solver_feedback(b))
        self.assertEqual(f.solver_feedback(a)['decision'],'revise')
        self.assertEqual(f.solver_feedback(a)['concerns'][0]['feedback'],raw['concerns'][0]['feedback'])
        self.assertNotIn('basis',json.dumps(f.solver_feedback(a)))
        self.assertNotIn('public_refs',json.dumps(f.solver_feedback(a)))
        for ref in ({'source_id':'private','start_line':1,'end_line':1},{'source_id':'artifact','start_line':1,'end_line':3}):
            invalid=deepcopy(raw);invalid['concerns'][0]['public_refs']=[ref]
            with self.assertRaises(ValueError):f.validate_output(invalid,trace_version='attack_defense_user_d0g1',instruction=ARGS['instruction'],current_artifact=ARGS['current_artifact'],max_concerns=3)

    def test_learned_path_unchanged(self):
        ref=recipe('attack_defense_v2.1')
        for v in f.VARIANTS:
            self.assertEqual(recipe(v),ref)
            self.assertEqual(prompt_hashes(v),prompt_hashes('attack_defense_v2.1'))

    def test_receipt_does_not_invent_emission_or_omission(self):
        with tempfile.TemporaryDirectory() as td:
            gen=_generation((_criterion(),));gen.red_team_trace_version='attack_defense_user_d1g0'
            selection=dict(criterion_id='elicited_x',source_generation=2,corrective=False,requirement='Check X')
            raw={'decision':'revise','concerns':[{'category':'task_fulfillment','feedback':'Finish the requested table.'}]}
            args=dict(root=Path(td),submission_id='s000',generation=gen,selection=selection,skipped=[],prompt='one ordinary prompt',user_feedback=raw,allow_generation=True)
            f.persist_budget_delivery(**args);args['allow_generation']=False;f.persist_budget_delivery(**args)
            rec=json.loads((Path(td)/'trace-defense-reminders/s000.json').read_text())
            for k in ('model_declared_association','semantic_exposure','omission_reason'):self.assertEqual(rec[k],'unknown')
            self.assertEqual(rec['rendered_feedback'],raw);self.assertEqual(rec['message_component'],'')

if __name__=='__main__':unittest.main()

class SimulatorFactorRoundtripTests(unittest.TestCase):
    def test_generated_grounded_record_revalidates_sources_without_resampling(self):
        from rubric_gen.submission_revision.user_simulator import SimulatedUserConfig,SimulatedUserFeedback,SimulatedUserGeneration
        calls=[]
        response={'decision':'revise','concerns':[{'category':'interpretation','feedback':'Check the displayed operands.',
          'basis':'verification_request','public_refs':[{'source_id':'artifact','start_line':1,'end_line':1}]}]}
        def generate(config,request):
            calls.append(request)
            return SimulatedUserGeneration(text=json.dumps(response),provider='openai',requested_model=config.model,
                effective_model=config.model,response_id='fixture',request_parameters={'max_output_tokens':config.max_output_tokens})
        sim=SimulatedUserFeedback(SimulatedUserConfig(model='gpt-5.6-luna'),generator=generate)
        gen=_generation(());gen.red_team_trace_version='attack_defense_user_d1g1'
        args=dict(experiment_id='exp',assignment_id='assignment',submission_id='s000',generation_round=2,generation=gen,
           instruction='Compute the sum.',current_artifact='1+2=3\n',history=(),history_summary=None,
           full_feedback={'score':10,'criteria':{},'rubric_text':'base','overall_reasoning':'Check sum'},
           trace_version=gen.red_team_trace_version,focused_dynamic_check=CHECK)
        with tempfile.TemporaryDirectory() as td:
            rec=sim.generate(**args,failure_dir=Path(td)/'failures')
            self.assertEqual(sim.validate(rec,**args),response)
            self.assertEqual(len(calls),1)
            broken=deepcopy(rec);broken['trace_factor_context']['source_bindings'][0][0]['text']='invented'
            with self.assertRaises(ValueError):sim.validate(broken,**args)
            self.assertEqual(len(calls),1)
