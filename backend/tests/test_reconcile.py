import math

from src.services.analysis import _allocation_weights, _exact_integers, reconcile


def result(values, model='holt', mae=1.0):
    future = {'holt': [{'prediction': v, 'raw': v, 'day': f'2026-11-{17 + i:02d}', 'clipped': False} for i, v in enumerate(values)],
              'seasonal_naive': [{'prediction': v, 'raw': v, 'day': f'2026-11-{17 + i:02d}', 'clipped': False} for i, v in enumerate(values)]}
    metrics = {'holt': {'mae': mae, 'mape': 0.0, 'mape_used': 7, 'zero_actual': 0},
               'seasonal_naive': {'mae': mae + 1, 'mape': 0.0, 'mape_used': 7, 'zero_actual': 0}}
    return {'future': future, 'metrics': metrics, 'selected_model': model}


def test_zero_error_weights_are_equal():
    assert _allocation_weights({'川北': 0.0, '川南': 0.0, '东河': 0.0}) == {'川北': 1 / 3, '川南': 1 / 3, '东河': 1 / 3}


def test_exact_integers_hits_target_and_never_negative():
    values = _exact_integers([10.4, 5.5, 0.1], 14)
    assert values == [11, 3, 0] or sum(values) == 14
    assert sum(values) == 14 and all(v >= 0 and isinstance(v, int) for v in values)
    for target in range(0, 40):
        out = _exact_integers([3.3, 2.2, 1.1], target)
        assert sum(out) == target and all(v >= 0 for v in out)


def test_reconcile_sums_match_region_every_day_and_reports_basis():
    region = result([100] * 7, mae=2.0)
    members = {'川北': result([40] * 7, mae=0.5), '川南': result([30] * 7, mae=4.0), '东河': result([20] * 7, mae=1.5)}
    data = reconcile(region, members)
    assert data['region_model'] == 'holt'
    for day in data['days']:
        assert day['after_sum'] == day['region'] == 100
        assert sum(v['after'] for v in day['branches'].values()) == 100
        assert all(v['after'] >= 0 for v in day['branches'].values())
        assert day['gap'] == 10
    # 误差最大的川南承担最多校正
    assert data['branches']['川南']['adjust_weight'] > data['branches']['川北']['adjust_weight']
    assert data['days'][0]['branches']['川南']['after'] > 30


def test_reconcile_zero_gap_keeps_raw_values():
    region = result([90] * 7)
    members = {'川北': result([40] * 7), '川南': result([25] * 7), '东河': result([25] * 7)}
    data = reconcile(region, members)
    for day in data['days']:
        assert day['gap'] == 0
        for branch, cell in day['branches'].items():
            assert cell['before'] == cell['after'] and cell['delta'] == 0
    assert all(day['after_sum'] == 90 for day in data['days'])


def test_reconcile_large_negative_gap_stays_non_negative():
    region = result([10] * 7)
    members = {'川北': result([100] * 7), '川南': result([100] * 7)}
    data = reconcile(region, members)
    for day in data['days']:
        assert day['after_sum'] == 10
        assert all(v['after'] >= 0 for v in day['branches'].values())
