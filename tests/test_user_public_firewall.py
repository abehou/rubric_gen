"""Information-flow and plumbing tests, not model-accuracy claims."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from rubric_gen.submission_revision import user_public_firewall as f
from rubric_gen.submission_revision.trace_defense_registry import recipe, prompt_hashes
from rubric_gen.submission_revision import trace_defense_delivery as delivery
from rubric_gen.submission_revision.user_simulator import SimulatedUserFeedback, SimulatedUserConfig, SimulatedUserGeneration
from test_user_delivery_v3 import _generation, _criterion

ARGS=dict(instruction='Report the estimate and uncertainty.\n',current_artifact='beta = -2\nresult = -beta\n',history_context='[]')
REF={'source_id':'artifact','start_line':1,'end_line':2}
ISSUE=dict(issue_type='implementation_check',public_refs=[REF],priority=1)
LOC=dict(decision='candidate_issue',issues=[ISSUE])
RENDER=dict(decision='verification_request',public_refs=[REF],concern=dict(category='calculation_correctness',feedback='Check the coefficient coding against the stated contrast.'))
VERIFY=dict(decision='unresolved_verification',public_refs=[REF],rationale='The contrast definition is not displayed here.')
PRIVATE='SECRET_RUBRIC criterion_987 secret expected PROTEIN_X 160 grader private reasoning'


def fake_provider(value):
    return SimulatedUserGeneration(text=json.dumps(value),provider='openai',requested_model='luna',effective_model='luna',response_id='r-test',request_parameters={'max_output_tokens':1024},provider_metadata={})


class PublicFirewallTests(unittest.TestCase):
    def setUp(self):
        self.docs=f.documents(**ARGS)

    def test_public_allowlist_cuts_raw_private_feedback(self):
        locator=f.locator_request(self.docs,PRIVATE,max_concerns=3,max_output_tokens=1024)
        self.assertIn(PRIVATE,locator.evidence)
        issue={**ISSUE,'private_source_id':PRIVATE,'private_reason':PRIVATE}
        for stage in ('verify','render'):
            request=f.review_request(self.docs,issue,stage=stage,max_output_tokens=1024)
            self.assertNotIn(PRIVATE,request.evidence)
            self.assertNotIn('private_source_id',request.evidence)
            payload=json.loads(request.evidence)
            self.assertEqual(set(payload),{'public_sources','candidate'})
            self.assertEqual(set(payload['candidate']),{'issue_type','public_refs'})
            self.assertNotIn('rubric',payload)
            self.assertNotIn('criterion_reason',payload)

    def test_private_wording_invariance_for_p1_and_p2(self):
        requests=[]
        for private in (PRIVATE,'another secret expected answer 999'):
            for version in f.VARIANTS:
                public=[]
                def call(name,request,verification):
                    if name=='locator': return deepcopy(LOC)
                    public.append(asdict(request))
                    return deepcopy(VERIFY if name.endswith('verify') else RENDER)
                f.pipeline(version,self.docs,private,max_concerns=3,max_output_tokens=1024,call=call)
                requests.append(public)
        self.assertEqual(requests[0],requests[2]); self.assertEqual(requests[1],requests[3])

    def test_locator_no_free_text_and_no_private_reference(self):
        request=f.locator_request(self.docs,PRIVATE,max_concerns=3,max_output_tokens=1024)
        for extra in ('concern','reason','expected_answer','private_source_id'):
            invalid=deepcopy(LOC);invalid['issues'][0][extra]=PRIVATE
            with self.assertRaises(ValueError): f.validate_against(invalid,request,self.docs)
        for ref in ({**REF,'source_id':'private'},{**REF,'end_line':99},{**REF,'start_line':True}):
            invalid=deepcopy(LOC);invalid['issues'][0]['public_refs']=[ref]
            with self.assertRaises(ValueError): f.validate_against(invalid,request,self.docs)
        extra=dict(self.docs,private=self.docs['artifact'])
        with self.assertRaises(ValueError):f.public_payload(extra)

    def test_public_references_exact_and_approved(self):
        docs=f.documents(instruction='Task\r\n',current_artifact='**均值**\r\n  beta=2\nlast',history_context='[]')
        request=f.locator_request(docs,PRIVATE,max_concerns=3,max_output_tokens=1024)
        bound=f.validate_against(LOC,request,docs)[0][0]
        self.assertEqual(bound['text'],'**均值**\r\n  beta=2\n')
        self.assertEqual(docs['artifact'].text.encode()[bound['byte_start']:bound['byte_end']],bound['text'].encode())

    def test_no_issue_does_not_call_renderer(self):
        call=Mock(return_value={'decision':'no_issue','issues':[]})
        for v in f.VARIANTS:
            self.assertEqual(f.pipeline(v,self.docs,PRIVATE,max_concerns=3,max_output_tokens=1024,call=call),{'decision':'accept','concerns':[]})
        self.assertEqual(call.call_count,2)

    def test_p2_unsupported_not_rendered(self):
        calls=[]
        def call(name,request,verification):
            calls.append(name)
            return LOC if name=='locator' else dict(decision='unsupported',public_refs=[REF],rationale='No public error is established.')
        self.assertEqual(f.pipeline('attack_defense_user_public_p2',self.docs,PRIVATE,max_concerns=3,max_output_tokens=1024,call=call),dict(decision='accept',concerns=[]))
        self.assertEqual(calls,['locator','issue-1-verify'])

    def test_verification_cannot_be_asserted_as_fact(self):
        request=f.review_request(self.docs,ISSUE,stage='render',max_output_tokens=1024,verification=VERIFY)
        invalid={**RENDER,'decision':'observed_defect'}
        with self.assertRaises(ValueError):f.validate_against(invalid,request,self.docs,verification=VERIFY)
        f.validate_against(RENDER,request,self.docs,verification=VERIFY)

    def test_renderer_metadata_stripped_and_budget(self):
        located=dict(decision='candidate_issue',issues=[{**ISSUE,'priority':i} for i in (1,2,3)])
        def call(name,request,verification):return located if name=='locator' else RENDER
        result=f.pipeline('attack_defense_user_public_p1',self.docs,PRIVATE,max_concerns=3,max_output_tokens=1024,call=call)
        self.assertEqual(len(result['concerns']),3)
        self.assertEqual(set(result['concerns'][0]),{'category','feedback'})
        for private in ('public_refs','source_id','priority','issue_type','SECRET_RUBRIC','criterion_987'):
            self.assertNotIn(private,json.dumps(result))
        self.assertNotIn('Focused review check',json.dumps(result))

    def test_complete_generator_native_record_replay_resume(self):
        for version in f.VARIANTS:
            with self.subTest(version=version),tempfile.TemporaryDirectory() as td:
                outputs=[LOC]+([VERIFY] if f.VARIANTS[version] else [])+[RENDER]
                generator=Mock(side_effect=[fake_provider(x) for x in outputs])
                sim=SimulatedUserFeedback(SimulatedUserConfig(model='luna'),generator=generator)
                gen=_generation((_criterion(),));gen.red_team_trace_version=version
                args=dict(experiment_id='test',assignment_id='a',submission_id='s000',generation_round=gen.generation_round,
                          instruction=ARGS['instruction'],generation=gen,full_feedback={'score':0,'criteria':[],'rubric_text':PRIVATE,'overall_reasoning':PRIVATE},
                          current_artifact=ARGS['current_artifact'],history=[],history_summary=None,trace_version=version)
                record=sim.generate(**args,failure_dir=Path(td))
                self.assertEqual(sim.validate(record,**args),record['output'])
                self.assertEqual(generator.call_count,len(outputs))
                second=sim.generate(**args,failure_dir=Path(td))
                self.assertEqual(record,second);self.assertEqual(generator.call_count,len(outputs))
                record['firewall_generation']['stages'][-1]['source_bindings']=[]
                with self.assertRaises(ValueError):sim.validate(record,**args)

    def test_valid_negative_never_retried(self):
        with tempfile.TemporaryDirectory() as td:
            generator=Mock(return_value=fake_provider({'decision':'no_issue','issues':[]}))
            sim=SimulatedUserFeedback(SimulatedUserConfig(model='luna'),generator=generator)
            record=f.execute(sim,version='attack_defense_user_public_p1',docs=self.docs,full_feedback_text=PRIVATE,directory=td)
            self.assertEqual(generator.call_count,1);self.assertEqual(record['output']['decision'],'accept')
            f.replay(sim,record,version='attack_defense_user_public_p1',docs=self.docs,full_feedback_text=PRIVATE)
            self.assertEqual(generator.call_count,1)

    def test_failed_contract_exhaustion_not_free_resampling(self):
        with tempfile.TemporaryDirectory() as td:
            invalid=deepcopy(LOC);invalid['issues'][0]['public_refs'][0]['end_line']=999
            generator=Mock(return_value=fake_provider(invalid))
            sim=SimulatedUserFeedback(SimulatedUserConfig(model='luna'),generator=generator)
            for _ in range(2):
                with self.assertRaises(RuntimeError):f.execute(sim,version='attack_defense_user_public_p1',docs=self.docs,full_feedback_text=PRIVATE,directory=td)
            self.assertEqual(generator.call_count,2)
            self.assertTrue((Path(td)/'locator/attempt-1.json').exists())

    def test_scientific_and_selector_implementation_shared(self):
        for version in f.VARIANTS:
            self.assertEqual(recipe(version),recipe('attack_defense_v2.1'))
            self.assertEqual(prompt_hashes(version),prompt_hashes('attack_defense_v2.1'))
        self.assertEqual(delivery.numeric_literals('160 52 0.05 20% 1e-3 -2 +.25 2E+4'),{'160','52','0.05','20%','1e-3','-2','+.25','2E+4'})

if __name__=='__main__':unittest.main()

class PublicFirewallResumeTests(unittest.TestCase):
    def test_interruption_after_paid_stage_resumes_missing_only(self):
        docs=f.documents(**ARGS)
        with tempfile.TemporaryDirectory() as td:
            first=Mock(side_effect=[fake_provider(LOC),KeyboardInterrupt('local controller interrupted')])
            sim=SimulatedUserFeedback(SimulatedUserConfig(model='luna'),generator=first)
            with self.assertRaises(KeyboardInterrupt):
                f.execute(sim,version='attack_defense_user_public_p1',docs=docs,full_feedback_text=PRIVATE,directory=td)
            sim._generator=Mock(return_value=fake_provider(RENDER))
            result=f.execute(sim,version='attack_defense_user_public_p1',docs=docs,full_feedback_text=PRIVATE,directory=td)
            self.assertEqual(sim._generator.call_count,1)
            self.assertEqual(result['output']['concerns'][0],RENDER['concern'])

    def test_locator_error_cannot_become_silent_accept(self):
        docs=f.documents(**ARGS)
        def call(name,request,verification):
            raise RuntimeError('provider failure')
        with self.assertRaises(RuntimeError):
            f.pipeline('attack_defense_user_public_p1',docs,PRIVATE,max_concerns=3,max_output_tokens=1024,call=call)
