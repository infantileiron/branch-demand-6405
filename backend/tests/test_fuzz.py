import random

from src.services.analysis import _exact_integers, reconcile


def _result(values, mae):
    day = [{'prediction': v, 'raw': v, 'day': f'd{i}', 'clipped': False} for i, v in enumerate(values)]
    metrics = {m: {'mae': mae + (0 if m == 'holt' else 1), 'mape': None, 'mape_used': 0, 'zero_actual': 7}
               for m in ('holt', 'seasonal_naive')}
    return {'future': {'holt': day, 'seasonal_naive': day}, 'metrics': metrics, 'selected_model': 'holt'}


def test_exact_integers_fuzz():
    rng = random.Random(7)
    for _ in range(1500):
        ideals = [rng.uniform(-60, 240) for _ in range(rng.randint(2, 8))]
        target = rng.randint(0, 700)
        out = _exact_integers(ideals, target)
        assert sum(out) == target
        assert all(isinstance(v, int) and v >= 0 for v in out)


def test_reconcile_fuzz_invariants():
    rng = random.Random(11)
    for _ in range(800):
        n = rng.randint(2, 8)
        region = _result([rng.randint(0, 300) for _ in range(7)], rng.uniform(0, 20))
        members = {f'b{i}': _result([rng.randint(0, 200) for _ in range(7)], rng.uniform(0, 20)) for i in range(n)}
        rec = reconcile(region, members)
        for d in rec['days']:
            assert d['after_sum'] == d['region']
            assert sum(c['after'] for c in d['branches'].values()) == d['region']
            assert all(c['after'] >= 0 for c in d['branches'].values())
            assert all(c['after'] - c['before'] == c['delta'] for c in d['branches'].values())
        assert abs(sum(rec['branches'][b]['adjust_weight'] for b in rec['branches']) - 1) < 1e-12
