"""Descriptive ranks retain direction, ties and undefined correlations."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rank = load('existing_gap_ranking', ROOT / 'experiments/trace-attack-defense-v3/artifact_gap_rh_ranking.py')
synthesis = load('mission_synthesis', ROOT / 'experiments/biomnibench-v21-to45/queue8/synthesize.py')


def test_high_gap_has_high_severity_with_average_ties():
    rows = [dict(key=str(i), W_minus_S=v, S_minus_H=v, H_minus_A=v)
            for i, v in enumerate([10, 10, 0, -5])]
    synthesis.severity_percentiles(rows, rank)
    assert [r['combined_severity_percentile'] for r in rows] == pytest.approx([100 * 2.5 / 3, 100 * 2.5 / 3, 100 / 3, 0])
    assert rows[0]['rank_W_minus_S'] == rows[1]['rank_W_minus_S'] == 1.5


def test_constant_scores_are_undefined_and_tie_overlap_is_fractional():
    assert rank.spearman([1, 1, 1], [1, 2, 3]) is None
    assert rank.kendall_tau_b([1, 1, 1], [1, 2, 3]) is None
    values = {str(i): 0 for i in range(10)}
    overlap = rank.overlap(values, values, .2)
    assert overlap['expected_overlap_count'] == pytest.approx(.4)
    assert overlap['expected_overlap_fraction'] == pytest.approx(.2)


def test_missing_monitor_is_retained_but_not_made_negative_or_zero():
    rows = []
    for i, score in enumerate([None, 2, 8]):
        row = dict(key=str(i), W_minus_S=i, S_minus_H=i, H_minus_A=i)
        for w in ('final_artifact', 'full_trajectory'):
            row['RH_' + w + '_monitor'] = score
            row['RH_' + w + '_status'] = 'ambiguous' if score is None else 'positive' if score > 5 else 'negative'
        rows.append(row)
    result = rank.analyze(rows)
    synthesis.severity_percentiles(rows, rank)
    assert len(rows) == 3 and rows[0]['RH_final_artifact_monitor'] is None
    assert result['final_artifact']['n'] == 2
    assert result['final_artifact']['missing_panel_scores'] == 1
    assert result['final_artifact']['ambiguous']['count'] == 1
