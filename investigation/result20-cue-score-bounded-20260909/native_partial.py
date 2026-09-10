"""Native analysis with an explicit infrastructure-only source-population adapter."""
import importlib.util,sys,inspect,json
from pathlib import Path
helper_path=Path(sys.argv.pop(1))
spec=importlib.util.spec_from_file_location('producer_native_analysis',helper_path)
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
import check_audit_coverage as coverage
original=coverage.source_records
allowed_study=Path('/home/aydanh/repos/rubric_gen/runs/babel-result20-cue-score-bounded-20260909/static/study/biomnibench-da-factorial-r10-f0203f5d69f3')
expected_records=json.loads(Path('/home/aydanh/repos/rubric_gen/investigation/result20-cue-score-preempt-repair-20260909/invalid-source-records.json').read_text())
expected_ids={r['assignment_id'] for r in expected_records};assert len(expected_ids)==6
expected_excluded=[dict(assignment_id=aid,error_type='RuntimeError',status='failed') for aid in sorted(expected_ids)]
def completed_source_records(study):
 records=original(study)
 failed=[r for r in records if r['status']!='completed']
 if failed:
  assert Path(study).resolve()==allowed_study
  assert len(failed)==6 and {r['assignment_id'] for r in failed}==expected_ids
  assert all(r['status']=='failed' and r['error']=='live workspace changed after the last checkpoint' for r in failed)
 return [r for r in records if r['status']=='completed']
coverage.source_records=completed_source_records
helper.source_records=completed_source_records
# Keep all native raw-record checks; account for the one declared failed source
# separately from the180 inactive assignments. Never rewrite saved coverage.
check_source=inspect.getsource(coverage.check)
old='assert summary["assignment_coverage"]["excluded_assignment_count"] == 0, name'
new='expected_exclusions = 6 if Path(study).resolve() == allowed_study else 0\n        assert summary["assignment_coverage"]["excluded_assignment_count"] == expected_exclusions, name\n        if expected_exclusions:\n            assert sorted(summary["assignment_coverage"]["excluded_assignments"], key=lambda r:r["assignment_id"]) == expected_excluded, name'
assert check_source.count(old)==1
check_source=check_source.replace(old,new)
old='len(ledger["records"]) - len(ids), name'
assert check_source.count(old)==1
check_source=check_source.replace(old,'len(ledger["records"]) - len(ids) - expected_exclusions, name')
namespace=dict(coverage.__dict__,allowed_study=allowed_study,expected_excluded=expected_excluded)
exec(compile(check_source, str(Path(__file__).resolve()), 'exec'),namespace)
helper.check=namespace['check']
helper.main()
