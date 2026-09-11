"""Run the canonical nine-assignment User attack_defense_v2.1 dev3 control."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json, os, socket, subprocess, sys, threading, time
from collections import Counter
from pathlib import Path
from dotenv import dotenv_values
from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study import StudyRunner, StudyRunConfig, _exclusive_study_lease
from rubric_gen.submission_revision.study_validation import validate_completed_revision
from rubric_gen.submission_revision.execution_scope import terminal_records

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
FLAVOR = os.environ.get('TRACE_V3_CONTROL_FLAVOR', 'control-v21')
RUN = Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911') / FLAVOR
TASKS = ('da-3-4', 'da-11-1', 'da-18-1')

def config_receipt(path):
    exp = load_experiment(path)
    task = exp.task_ids[0]
    expected = {(task, rep, 'user-simulator-red-team-trace') for rep in range(1, 4)}
    actual = {(a.task_id, a.replicate, a.condition_id) for a in exp.execution_assignments}
    if actual != expected or len(exp.execution_assignments) != 3:
        raise RuntimeError(f'control scope differs: {sorted(actual)}')
    if exp.protocol.get('red_team_trace_version') != 'attack_defense_v2.1':
        raise RuntimeError('control is not attack_defense_v2.1')
    if exp.payload['randomization'] != {'seed': 20260806, 'replicates': 3}:
        raise RuntimeError('canonical dev3 randomization changed')
    if exp.protocol['min_revisions'] != 5 or exp.protocol['max_revisions'] != 10:
        raise RuntimeError('revision boundary changed')
    return exp

def prepare(runner):
    existed = runner.root.exists()
    runner.root.mkdir(parents=True, exist_ok=True)
    with _exclusive_study_lease(runner.root):
        runner._start_manifest(sorted(runner.experiment.assignments, key=lambda a: a.execution_order), existed)
        runner._prepare_pretreatment_rubric(runner.experiment.task_ids[0])

def main():
    if not os.environ.get('SLURM_JOB_ID') or int(os.environ.get('SLURM_CPUS_PER_TASK', '0')) != 32:
        raise RuntimeError('control requires a 32-CPU Slurm allocation')
    runtime = policy()
    if runtime['aggregate_concurrency'] != 60 or runtime['audit_studies'] != 1:
        raise RuntimeError('shared capacity policy differs')
    credentials = dotenv_values('/home/aydanh/repos/rubric_gen/.env.local')
    if not credentials.get('OPENAI_API_KEY'):
        raise RuntimeError('configured OpenAI credential absent')
    os.environ['OPENAI_API_KEY'] = str(credentials['OPENAI_API_KEY'])
    exps = [config_receipt(BUNDLE / FLAVOR / f'{task}.yaml') for task in TASKS]
    owner = RUN / 'owners' / os.environ['SLURM_JOB_ID']; owner.mkdir(parents=True, exist_ok=True)
    write_json_atomic(owner / 'launch.json', {
        'method': 'attack_defense_v2.1', 'dev3_control': True, 'flavor': FLAVOR, 'job': os.environ['SLURM_JOB_ID'],
        'host': socket.gethostname(), 'commit': subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
        'runtime': runtime, 'cpus': 32, 'assignment_workers': 9, 'learning_fanout': 4,
        'tasks': list(TASKS), 'expected_assignments': 9,
        'configs': {str(e.path): sha256_file(e.path) for e in exps},
        'time': datetime.now(timezone.utc).isoformat(), 'outcome_audits': False,
    })
    runners = [StudyRunner(StudyRunConfig(e, Path(e.dag['seed']['output_dir']), Path(e.dag['paraphrase']['output_dir']), Path(e.dag['revise']['output_dir']), 3, resume=Path(e.dag['revise']['output_dir']).exists())) for e in exps]
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(prepare, runners))
    # Preparation creates the native study manifest; resume it explicitly before
    # scheduling assignments, matching the validated dev3 runner's handoff.
    runners = [StudyRunner(StudyRunConfig(r.experiment, r.seed_root, r.paraphrase_root, r.root, 3, resume=True)) for r in runners]
    frozen_g1 = []
    for runner in runners:
        for p in runner.pretreatment_root.glob('**/generation-0001/manifest.json'):
            d = json.loads(p.read_text())
            frozen_g1.append({'task': runner.experiment.task_ids[0], 'manifest': str(p), 'manifest_sha256': sha256_file(p), 'generation_sha256': d['generation_sha256']})
    if len(frozen_g1) != 3:
        raise RuntimeError(f'expected three reused g1 manifests, found {len(frozen_g1)}')
    write_json_atomic(RUN / 'frozen-g1.json', frozen_g1)
    stop = threading.Event()
    def monitor():
        while not stop.is_set():
            rows = []
            for runner in runners:
                try: rows.extend(json.loads((runner.root/'study.json').read_text())['records'])
                except (OSError, ValueError, KeyError): pass
            write_json_atomic(BUNDLE / f'{FLAVOR}-status.json', {'job': os.environ['SLURM_JOB_ID'], 'flavor': FLAVOR, 'statuses': dict(Counter(r['status'] for r in rows)), 'time': datetime.now(timezone.utc).isoformat()})
            stop.wait(30)
    threading.Thread(target=monitor, daemon=True).start()
    start = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=3) as pool: exits = list(pool.map(lambda r: r.run(), runners))
    finally: stop.set()
    write_json_atomic(owner / 'revision-exits.json', {'exits': exits, 'wall_seconds': time.monotonic() - start})
    if any(exits): raise RuntimeError('control has incomplete assignments; successful outputs retained')
    rows = []
    for runner in runners:
        ledger = json.loads((runner.root/'study.json').read_text())
        completed = terminal_records(runner.experiment, ledger)
        if len(completed) != 9 / 3 or any(r['status'] != 'completed' for r in completed):
            raise RuntimeError('task study scope incomplete')
        assignments = {a.assignment_id: a for a in runner.experiment.assignments}
        for record in completed:
            path = runner.root / record['experiment_dir']
            validate_completed_revision(path, assignments[record['assignment_id']], runner.experiment, runner.seed_root, runner.paraphrase_root)
            rows.append({'assignment_id': record['assignment_id'], 'root': str(path), 'experiment_id': runner.experiment.experiment_id})
    write_json_atomic(RUN / 'completion.json', {'method':'attack_defense_v2.1', 'dev3_control':True, 'flavor': FLAVOR, 'job':os.environ['SLURM_JOB_ID'], 'expected':9, 'completed':len(rows), 'assignments':rows, 'frozen_g1':frozen_g1, 'audits_launched':0})
    print(json.dumps({'stage':'dev3_control_complete','assignments':len(rows),'outcome_audits':0}), flush=True)

if __name__ == '__main__': main()
