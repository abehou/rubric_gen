import contextlib,importlib.util,json,os,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
module=types.ModuleType('rubric_gen.submission_revision.study');module._exclusive_study_lease=lambda _:contextlib.nullcontext()
with patch.dict(sys.modules,{'rubric_gen.submission_revision.study':module}):
 spec=importlib.util.spec_from_file_location('archive_invalid',Path(__file__).with_name('archive_invalid.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ArchiveTests(unittest.TestCase):
 def test_valid_archive_preserves_completed_and_manifest(self):
  with tempfile.TemporaryDirectory() as tmp:
   base=Path(tmp);study=base/'static/study/biomnibench-da-factorial-r10-f0203f5d69f3';study.mkdir(parents=True)
   records=[dict(assignment_id=f'completed-{i}',condition_id='user-simulator-static',status='completed') for i in range(58)]
   for aid,error in m.EXPECTED.items():
    records.append(dict(assignment_id=aid,condition_id='user-simulator-static',status='failed',error=error))
    task,rep,_,condition=aid.split('--');p=study/'experiments'/task/rep/'luna'/condition;p.mkdir(parents=True);(p/'evidence').write_text(aid)
   marker=study/'completed-evidence';marker.write_text('keep');manifest=study/'study.json';manifest.write_text(json.dumps({'records':records}));before=manifest.read_bytes()
   with patch.object(m,'BASE',base),patch.dict(os.environ,SLURM_JOB_ID='test'),patch.object(m.subprocess,'check_output',side_effect=['','10364765|FAILED\n']):m.main()
   self.assertEqual(manifest.read_bytes(),before);self.assertEqual(marker.read_text(),'keep')
   archive=base/'invalid-attempts/pre-fresh-test';self.assertEqual(len(json.loads((archive/'manifest.json').read_text())['moves']),2)
   for aid in m.EXPECTED:self.assertEqual((archive/aid/'evidence').read_text(),aid)
 def test_live_owner_rejected(self):
  with patch.dict(os.environ,SLURM_JOB_ID='test'),patch.object(m.subprocess,'check_output',return_value='10364765\n'):
   with self.assertRaisesRegex(RuntimeError,'active'):m.main()
 def test_nonterminal_accounting_rejected(self):
  with patch.dict(os.environ,SLURM_JOB_ID='test'),patch.object(m.subprocess,'check_output',side_effect=['','10364765|RUNNING|\n']):
   with self.assertRaisesRegex(RuntimeError,'terminal'):m.main()
if __name__=='__main__':unittest.main()
