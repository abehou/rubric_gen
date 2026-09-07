from rubric_gen.submission_revision.evolution_assessment import pair_text_difference


def test_difference_exposes_small_material_edit_in_long_shared_context():
    prefix = '\n'.join(f'unchanged row {i}' for i in range(300))
    a = prefix + '\nk = len(shared_genes & g2m)\n'
    b = prefix + '\nshared_gene_rows = list(shared_genes) + ["ABL1"]\nk = sum(g in g2m for g in shared_gene_rows)\n'
    result = pair_text_difference(a, b)
    assert '+shared_gene_rows = list(shared_genes) + ["ABL1"]' in result['text']
    assert '-k = len(shared_genes & g2m)' in result['text']
    assert result['truncated'] is False
    assert 'unchanged row 0\n' not in result['text']


def test_identical_text_has_no_implied_quality_preference():
    assert pair_text_difference('same\n', 'same\n')['text'] == ''
    result = pair_text_difference('before\n', 'after\n')
    assert set(result) == {'format', 'text', 'truncated'}
    assert '--- artifact_A' in result['text'] and '+++ artifact_B' in result['text']
    reverse = pair_text_difference('after\n', 'before\n')['text']
    assert '-after' in reverse and '+before' in reverse


def test_large_unicode_diff_is_bounded_and_explicitly_truncated():
    result = pair_text_difference('α' * 10000, 'β' * 10000)
    assert len(result['text'].encode('utf-8')) <= 8192
    assert result['truncated'] is True
    assert '\ufffd' not in result['text']
