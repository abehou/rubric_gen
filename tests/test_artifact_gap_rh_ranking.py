"""Provider-free statistical/reporting checks; no model-accuracy claims."""
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'experiments/trace-attack-defense-v3/artifact_gap_rh_ranking.py'
spec = importlib.util.spec_from_file_location('gap_ranking', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RankingTests(unittest.TestCase):
    def test_high_gap_is_worst_and_aligned_monitor_is_positive(self):
        rows = []
        for i in range(4):
            rows.append(dict(key=str(i), W_minus_S=i, S_minus_H=i, H_minus_A=i,
                RH_final_artifact_monitor=i, RH_full_trajectory_monitor=i,
                RH_final_artifact_status='negative', RH_full_trajectory_status='negative'))
        result = module.analyze(rows)['final_artifact']
        self.assertEqual(rows[-1]['combined_gap_rank'], 1)
        self.assertEqual(result['metrics']['combined_gap_score']['spearman'], 1)
        self.assertEqual(result['combined_gap_rank_vs_monitor']['spearman'], -1)
        self.assertEqual(result['metrics']['combined_gap_score']['worst_overlap']['25']['expected_overlap_fraction'], 1)

    def test_ties_do_not_use_task_identifier_to_pick_worst_cases(self):
        values = {str(i): 0 for i in range(4)}
        self.assertEqual(module.tie_rank(values), {str(i): 2.5 for i in range(4)})
        result = module.overlap(values, values, .25)
        self.assertEqual(result['expected_overlap_fraction'], .25)
        self.assertEqual(sum(result['gap_boundary_members'].values()), 1)
        self.assertIsNone(module.spearman([0, 0], [1, 2]))

    def test_aggregate_requires_complete_panel_and_preserves_ambiguous(self):
        def row(model, decision, score):
            return dict(task_id='example', replicate=1, model=model,
                values={k: 0 for k in ('W','W_train','S','H','A','W_minus_S','W_minus_A','S_minus_H','H_minus_A')},
                direct={w: dict(decision=decision,score=score) for w in module.WINDOWS})
        a = row(module.PANEL[0], 'abstain', None)
        b = row(module.PANEL[1], 'no_reward_hacking_detected', 0)
        result = module.aggregate([a, b], label='example')[0]
        self.assertEqual(result['RH_final_artifact_status'], 'ambiguous')
        self.assertIsNone(result['RH_final_artifact_monitor'])
        stats = module.analyze([result])['final_artifact']
        self.assertEqual(stats['negative']['count'], 0)
        self.assertEqual(stats['ambiguous']['count'], 1)
        with self.assertRaises(ValueError): module.aggregate([a], label='example')
        with self.assertRaises(ValueError): module.aggregate([a, a], label='example')

    def test_positive_union_and_equal_weight_scores(self):
        rows = [dict(task_id='example', replicate=1, model=model,
            values={k: float(i) for k in ('W','W_train','S','H','A','W_minus_S','W_minus_A','S_minus_H','H_minus_A')},
            direct={w: dict(decision='reward_hacking_detected' if i else 'abstain', score=float(i)) for w in module.WINDOWS})
            for i, model in enumerate(module.PANEL)]
        result = module.aggregate(rows,label='example')[0]
        self.assertEqual(result['A'], .5)
        self.assertEqual(result['RH_final_artifact_status'], 'positive')
        self.assertTrue(result['RH_final_artifact_abstain'])
        self.assertEqual(result['RH_final_artifact_monitor'], .5)

if __name__ == '__main__': unittest.main()
