"""Export the completed local result tables and evidence-linked corrections, offline."""
from rubric_gen.runtime.process_environment import install_controlled_process_environment
install_controlled_process_environment()
from collections import Counter
from pathlib import Path
from statistics import mean
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUN = ROOT / 'runs/healthbench-haiku50-20261009'
METRICS = ('W', 'S', 'H', 'A', 'W-S', 'S-H', 'H-A')
WINDOWS = ('full_trajectory', 'post_update', 'final_revision', 'final_artifact')
ORDER = [(p+'-'+f, n+' × '+l) for p,n in [('full','Full'),('semi','Semi'),
    ('score-only','Score-only'),('user-simulator','User')]
    for f,l in [('static','Static'),('red-team-trace','RTT')]]
YES = 'reward_hacking_detected'


def read(p):
    return json.loads(p.read_text())


def portable(value):
    if isinstance(value, str):
        return value.replace(str(ROOT)+'/', '')
    if isinstance(value, list):
        return [portable(x) for x in value]
    if isinstance(value, dict):
        return {k: portable(v) for k,v in value.items()}
    return value


def check(data):
    assert len(data['rows']) == 1200
    identities = {(r['source_id'],r['condition_id'],r['replicate']) for r in data['rows']}
    assert len(identities) == 1200
    for c,_ in ORDER:
        rows = [r for r in data['rows'] if r['condition_id']==c]
        assert len(rows)==150 and len({r['source_id'] for r in rows})==50
        assert set(Counter(r['source_id'] for r in rows).values())=={3}
        for m in METRICS:
            assert abs(mean(r['final'][m] for r in rows)-data['conditions'][c]['final'][m])<1e-9
        for r in rows:
            for gap in ('W-S','S-H','H-A'):
                a,b = gap.split('-')
                assert abs(r['final'][gap]-(r['final'][a]-r['final'][b]))<1e-9
        for w in WINDOWS:
            assert dict(Counter(r[w]['decision'] for r in rows)) == data['conditions'][c][w]['decisions']
    return identities


def table(data):
    lines = ['| Condition | W | S | H | A | W−S | S−H | H−A | Full trajectory RH | Final artifact RH |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for c,label in ORDER:
        d=data['conditions'][c]
        nums=[d[w]['decisions'].get(YES,0) for w in ('full_trajectory','final_artifact')]
        lines.append('| '+label+' | '+' | '.join(f"{d['final'][m]:.2f}" for m in METRICS)+' | '+
                     ' | '.join(f'{n}/150 ({n/150:.1%})' for n in nums)+' |')
    return '\n'.join(lines)


def main():
    haiku=read(RUN/'corrected-analysis.json')
    luna=read(ROOT/'experiments/healthbench-hard-result50/results.json')
    assert check(haiku)==check(luna)
    earlier=read(RUN/'review/rh-focus/previous-analysis.json')
    assert all(r['final']==p['final'] and r['rounds']==p['rounds']
               for r,p in zip(haiku['rows'],earlier['rows'],strict=True))
    luna_local=read(ROOT/'runs/healthbench-hard-result50-extension-20261006/corrected-analysis.json')
    assert check(luna_local)==check(luna)
    ll={(r['source_id'],r['condition_id'],r['replicate']):r for r in luna_local['rows']}
    assert all(r['final']==ll[r['source_id'],r['condition_id'],r['replicate']]['final'] for r in luna['rows'])
    same_seeds=set()
    for row in haiku['rows']:
        other=ll[row['source_id'],row['condition_id'],row['replicate']]
        assert (ROOT/row['rounds'][0]['answer_path']).read_bytes()==(ROOT/other['rounds'][0]['answer_path']).read_bytes()
        same_seeds.add((row['source_id'],row['replicate']))
    assert len(same_seeds)==150
    compact = dict(tasks=50,replicates=3,assignments=1200,conditions=haiku['conditions'],
        source=str(RUN/'corrected-analysis.json'),
        definition='Saved-evidence corrected endpoints; original RH 0–10 scores retained, not manually rescored. '
                   'All150 assignments per condition remain in RH denominators, including abstentions.',
        models=dict(revision_solver='claude-haiku-5-5 low',W='claude-haiku-5-5 low',
                    user_simulator='claude-haiku-5-5 low',RTT='claude-haiku-5-5 high',
                    S_H_RH='gpt-6-luna high',A_pairwise='gpt-6-sol high',
                    initial_answers='150 reused Luna seed answers, byte-identical to Luna50'),
        rows=[{k:r[k] for k in ('task_id','source_id','condition_id','replicate','initial','final','rounds',*WINDOWS)}
              for r in haiku['rows']],verification=haiku['verification'])
    corrections=dict(first_review=read(RUN/'review/corrections.json'),
                     rh_followup=read(RUN/'review/rh-focus/corrections.json'))
    for filename,obj in [('results.json',compact),('review-corrections.json',corrections)]:
        (HERE/filename).write_text(json.dumps(portable(obj),ensure_ascii=False)+'\n')
    lines=['# HealthBench Hard Haiku Result50', '',
        '50 tasks ×8 conditions ×3 replicates,3 revision rounds;150 trajectories per condition. '
        'Scores/gaps use0–100; RH uses positives/all150, including abstentions.', '',
        'The tables include the completed saved-evidence S/H and RH corrections. Original audit records and numeric RH scores are retained; '
        'the latest RH-only review does not change W/S/H/A, gaps, answers or population.', '',
        '## Haiku50 — current results', '',table(haiku), '',
        '## Luna50 — previously published results', '',table(luna), '',
        '## Matched comparison', '',
        'Both runs cover the same50 source tasks and3 replicates; all150 initial answer files match byte-for-byte. '
        'Haiku replaces the revision solver, online W and user simulator, and RTT components; this is not a Haiku-from-scratch seed run. '
        'Both use6Luna-high S/H/RH and6Sol-high A/pairwise. W uses a different model in each run, so it is not a common-judge quality comparison.', '',
        '| Policy | Haiku full RH: Static → RTT | Luna full RH: Static → RTT | Haiku A: Static → RTT | Luna A: Static → RTT |',
        '|---|---:|---:|---:|---:|']
    for prefix,label in [('full','Full'),('semi','Semi'),('score-only','Score-only'),('user-simulator','User')]:
        cells=[]
        for data in (haiku,luna):
            ds=[data['conditions'][prefix+'-'+f] for f in ('static','red-team-trace')]
            cells.append(' → '.join(f"{d['full_trajectory']['decisions'].get(YES,0)/150:.1%}" for d in ds))
        for data in (haiku,luna):
            cells.append(' → '.join(f"{data['conditions'][prefix+'-'+f]['final']['A']:.2f}" for f in ('static','red-team-trace')))
        lines.append('| '+label+' | '+' | '.join(cells)+' |')
    lines += ['',
        '- Full-trajectory RH is lower for RTT than Static in each of the four policies in both reported tables. '
        'Haiku reductions are11.33,2.00,1.33,0.67 percentage points; Luna reductions are6.00,2.00,1.33,2.67.',
        '- Haiku full-trajectory RH is higher than Luna in all eight cells. Its A scores are3.74–7.59 points lower across the matched cells; '
        'this is a between-run difference, not a claim of within-run degradation.',
        '- Within Haiku, RTT minus Static S−H is−3.19/−1.92/−4.40/−1.43 points (Full/Semi/Score-only/User). '
        'These are signed gap differences; negative gaps do not by themselves demonstrate better independent quality.', '',
        '## Verification and evidence', '',
        '- [Machine-readable results](results.json): all1200 assignment endpoints and RH judgments.',
        '- [Correction evidence](review-corrections.json): prior criterion/RH corrections and the latest22 RH-window changes, with saved evidence paths and reasons.',
        '- [Offline export/verification](publish_results.py): checks population, aggregates, gap arithmetic, all RH windows, unchanged score fields and shared initial answers.',
        '- Local originals: `runs/healthbench-haiku50-20261009/{matrix-analysis.json,review/}`. Referenced run artifacts remain local, not bundled into this Git publication.',
        '- [Previously published Luna50](../healthbench-hard-result50/RESULTS.md).', '',
        'This publication performs no API calls and changes no experimental outcomes.', '']
    (HERE/'RESULTS.md').write_text('\n'.join(lines))
    print(json.dumps(dict(status='passed',matched_assignments=1200,byte_identical_seeds=150,
                         exported=['RESULTS.md','results.json','review-corrections.json'],api_cost=0)))


if __name__=='__main__':
    main()
