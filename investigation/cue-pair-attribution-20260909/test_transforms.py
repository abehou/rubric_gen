import json
import unittest
from transforms import difference, swap, preferred_ids

class TransformTests(unittest.TestCase):
    def evidence(self):
        return {'task':'Frozen task', 'assessment_view':'rubric_free', 'artifacts':[{'artifact_id':'one','content':'trace 10\nanswer 10'},{'artifact_id':'two','content':'trace 10\nanswer 11'}], 'pairs':[{'pair_id':'p','artifact_A':{'artifact_id':'one'},'artifact_B':{'artifact_id':'two'},'visible_difference':difference('trace 10\nanswer 10','trace 10\nanswer 11')}]}
    def test_involution_and_unchanged_context(self):
        e=self.evidence();s=swap(json.dumps(e))
        self.assertEqual(swap(json.dumps(s)),e)
        self.assertEqual(s['artifacts'],e['artifacts'])
        self.assertEqual(s['task'],e['task'])
        self.assertEqual(s['pairs'][0]['artifact_A']['artifact_id'],'two')
    def test_preference_identity_invariant(self):
        e=self.evidence();s=swap(json.dumps(e))
        self.assertEqual(preferred_ids(e,{'assessments':[{'pair_id':'p','preference':'artifact_A'}]}),preferred_ids(s,{'assessments':[{'pair_id':'p','preference':'artifact_B'}]}))
    def test_reject_stale_diff(self):
        e=self.evidence();e['pairs'][0]['visible_difference']['text']='wrong'
        with self.assertRaises(ValueError):swap(json.dumps(e))
    def test_reject_missing_judgment(self):
        with self.assertRaises(ValueError):preferred_ids(self.evidence(),{'assessments':[]})

if __name__=='__main__':unittest.main()
