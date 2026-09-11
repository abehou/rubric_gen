"""Saved exposure and later optimizer levels; observations are not compliance proof."""
import argparse
from collections import Counter
import csv
import json
import os
from pathlib import Path
from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.trace_defense_binding import load_binding
from rubric_gen.submission_revision.rubric_generation import RubricPolicy
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation

ROOT = Path(__file__).resolve().parents[2]
RUN = Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910')


def read(path):
    return json.loads(path.read_bytes())


def main(subversion):
    cohort = RUN/'dev3'/subversion
    public = ROOT/'docs/reports/2026-09-10/trace-attack-defense-v2/dev3'/subversion
    completion, integrity = read(cohort/'completion.json'), read(public/'integrity.json')
    observations, rules = [], []
    for assignment in completion['assignments']:
        root = Path(assignment['root'])
        manifest = read(root/'manifest.json')
        common = {k: manifest[k] for k in ('assignment_id', 'task_id', 'replicate', 'condition_id')}
        common['arm'] = 'user' if 'user-simulator' in common['condition_id'] else 'full'
        exposures = [r for r in integrity['active_rule_exposures'] if r['assignment_id'] == assignment['assignment_id']]
        validations = {sha256_file(p): p for p in (root/'judgments').glob('**/score_validation.json')}
        local, criteria = [], {}
        for path in sorted((root/'submission-rubric-bindings').glob('s*.json')):
            binding = load_binding(root, path.stem)
            checkpoint = int(path.stem[1:])
            generation = load_rubric_generation(root, binding['active_generation_round'], expected_policy=RubricPolicy.RED_TEAM_TRACE)
            evaluation = read(root/'rubric-evaluations'/path.name)
            score_path = validations[evaluation['score_validation_sha256']]
            score = read(score_path)
            offset = len(score['criterion_scores'])-len(generation.elicited_criteria)+1
            for index, criterion in enumerate(generation.elicited_criteria, offset):
                if criterion.source_generation < 2:
                    continue
                cid, native = criterion.criterion_id, f'criterion_{index}'
                criteria[cid] = criterion
                previous = [r for r in exposures if r['criterion_id'] == cid and r['solver_turn'] <= checkpoint]
                upcoming = [r for r in exposures if r['criterion_id'] == cid and r['solver_turn'] == checkpoint+1]
                local.append({**common, 'submission_id': path.stem, 'criterion_id': cid,
                    'source_generation': criterion.source_generation, 'active_generation': generation.generation_round,
                    'level': score['criterion_levels'][native], 'points': score['criterion_scores'][native],
                    'after_observed_exposure': bool(previous),
                    'after_focused_reminder': any(r['focused'] for r in previous),
                    'delivered_for_next_turn': bool(upcoming), 'feedback_opportunity': binding['feedback_opportunity'],
                    'validation_path': str(score_path), 'validation_sha256': sha256_file(score_path),
                    'binding_sha256': binding['binding_sha256']})
        observations.extend(local)
        for cid, criterion in criteria.items():
            scored = [r for r in local if r['criterion_id'] == cid]
            delivered = [r for r in exposures if r['criterion_id'] == cid]
            later = [r for r in scored if r['after_observed_exposure']]
            first = min((r['solver_turn'] for r in delivered), default=None)
            rules.append({**common, 'criterion_id': cid, 'requirement': criterion.requirement,
                'source_generation': criterion.source_generation, 'first_available_turn': criterion.source_generation-1,
                'first_exposed_turn': first,
                'first_focused_turn': min((r['solver_turn'] for r in delivered if r['focused']), default=None),
                'availability_to_exposure_lag': first-(criterion.source_generation-1) if first is not None else None,
                'ordinary_deliveries': sum(r['ordinary_verbatim'] or r['ordinary_json_escaped'] for r in delivered),
                'focused_deliveries': sum(r['focused'] for r in delivered),
                'subsequent_scored_observations': len(later),
                'subsequent_scored_violations': sum(r['points'] < 0 for r in later),
                'subsequent_violation_response_opportunities': sum(r['points'] < 0 and r['feedback_opportunity'] for r in later),
                'first_subsequent_level': later[0]['level'] if later else None,
                'first_subsequent_points': later[0]['points'] if later else None})
    raw = cohort/'report/scored-online-rules.json'
    write_json_atomic(raw, observations)
    write_json_atomic(public/'online-rule-timing.json', rules)
    if rules:
        with (public/'online-rule-timing.csv').open('w') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rules[0]))
            writer.writeheader()
            writer.writerows(rules)
    summary = {arm: {'online_lineages': len(rows), 'actually_exposed': sum(r['first_exposed_turn'] is not None for r in rows),
                    'first_exposure_turn_histogram': dict(Counter(r['first_exposed_turn'] for r in rows)),
                    'first_subsequent_level_histogram': dict(Counter(r['first_subsequent_level'] for r in rows)),
                    'subsequent_observations': sum(r['subsequent_scored_observations'] for r in rows),
                    'subsequent_violations': sum(r['subsequent_scored_violations'] for r in rows)}
               for arm in ('full', 'user') if (rows := [r for r in rules if r['arm'] == arm])}
    # JSON object keys cannot mix null and integer types under canonical sorting.
    for values in summary.values():
        for key in ('first_exposure_turn_histogram', 'first_subsequent_level_histogram'):
            values[key] = {str(k): v for k, v in values[key].items()}
    write_json_atomic(public/'timing-summary.json', {'arms': summary,
        'scored_observations': {'path': str(raw), 'sha256': sha256_file(raw), 'rows': len(observations)},
        'limitations': ['Later levels are optimizer judgments, not independent evidence of compliance or lower RH.',
                       'Absent verbatim exposure does not exclude a related simulated-user paraphrase.',
                       'No-change termination can leave exposure without a subsequent scored submission.',
                       'Lineage observations repeat within assignments; they are not independent cases.']})
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    if not os.environ.get('SLURM_JOB_ID'):
        raise RuntimeError('compute storage requires Slurm')
    parser = argparse.ArgumentParser()
    parser.add_argument('subversion')
    main(parser.parse_args().subversion)
