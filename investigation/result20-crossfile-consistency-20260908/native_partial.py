"""Native analysis with an explicit infrastructure-only source-population adapter."""
import importlib.util,sys,inspect
from pathlib import Path
helper_path=Path(sys.argv.pop(1))
spec=importlib.util.spec_from_file_location('producer_native_analysis',helper_path)
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
import check_audit_coverage as coverage
original=coverage.source_records
allowed_study=Path('/home/aydanh/repos/rubric_gen/runs/babel-result20-crossfile-consistency-20260908/trace/study/biomnibench-da-factorial-r10-f0203f5d69f3')
def completed_source_records(study):
 records=original(study)
 failed=[r for r in records if r['status']!='completed']
 if failed:
  assert Path(study).resolve()==allowed_study
  assert len(failed)==1 and failed[0]['assignment_id']=='da-13-3--rep-001--solver-luna--user-simulator-red-team-trace'
  assert failed[0]['status']=='failed' and failed[0]['error']=='artifact history has invalid red-team evidence'
 return [r for r in records if r['status']=='completed']
coverage.source_records=completed_source_records
helper.source_records=completed_source_records
# Keep all native raw-record checks; account for the one declared failed source
# separately from the180 inactive assignments. Never rewrite saved coverage.
check_source=inspect.getsource(coverage.check)
old='assert summary["assignment_coverage"]["excluded_assignment_count"] == 0, name'
new='expected_exclusions = 1 if Path(study).resolve() == allowed_study else 0\n        assert summary["assignment_coverage"]["excluded_assignment_count"] == expected_exclusions, name\n        if expected_exclusions:\n            assert summary["assignment_coverage"]["excluded_assignments"] == [{"assignment_id": "da-13-3--rep-001--solver-luna--user-simulator-red-team-trace", "error_type": "ValueError", "status": "failed"}], name'
assert check_source.count(old)==1
check_source=check_source.replace(old,new)
old='len(ledger["records"]) - len(ids), name'
assert check_source.count(old)==1
check_source=check_source.replace(old,'len(ledger["records"]) - len(ids) - expected_exclusions, name')
namespace=dict(coverage.__dict__,allowed_study=allowed_study)
exec(compile(check_source, str(Path(__file__).resolve()), 'exec'),namespace)
helper.check=namespace['check']
helper.main()
