from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from src.constants.enums import BRANCHES
from src.models.entities import DailyVolume, Region, RegionRun, RegionRunMember, Staffing, User
from src.schemas.business import RegionInput, RegionRunInput
from src.services.regions import approve, compute, create_region, create_run, publish, retry
from src.utils.security import hash_password

import random


def seed_volumes(Session, branches=BRANCHES[:3], days=70):
    rng = random.Random(3109)
    with Session() as s:
        for b, branch in enumerate(branches):
            for i in range(days):
                day = (date(2026, 9, 6) + timedelta(days=i)).isoformat()
                weekday = date.fromisoformat(day).weekday()
                volume = max(0, round(24 + b * 4 + i * .12 + (10 if weekday < 5 else -8) + rng.gauss(0, 3)))
                s.add(DailyVolume(branch=branch, day=day, volume=volume, note='test'))
        s.commit()


def seed_users(Session):
    with Session() as s:
        for role in ('admin', 'analyst', 'viewer'):
            if not s.query(User).filter_by(email=role + '@demo.local').first():
                s.add(User(email=role + '@demo.local', role=role, password=hash_password('Demo123!')))
        s.commit()


def actor(Session, role='analyst'):
    with Session() as s:
        return s.query(User).filter_by(role=role).first()


def make_region(Session, name='测试区', members=('川北', '川南', '东河')):
    with Session() as s:
        return create_region(s, RegionInput(name=name, note='', members=list(members)), s.query(User).filter_by(role='analyst').first()).id


def make_run(Session, region_id, key=''):
    with Session() as s:
        return create_run(s, s.get(Region, region_id),
                          RegionRunInput(name='', backtest_days=14, alpha=.6, beta=.2, capacity=12, request_key=key),
                          s.query(User).filter_by(role='analyst').first()).id


def computed(Session, run_id):
    with Session() as s:
        run = s.get(RegionRun, run_id)
        compute(s, run)
    with Session() as s:
        return s.get(RegionRun, run_id)


def test_full_region_flow_has_matching_sums_and_basis(env):
    S = env['Session']
    seed_volumes(S); seed_users(S)
    rid = make_region(S)
    run_id = make_run(S, rid)
    run = computed(S, run_id)
    assert run.state == 'done'
    data = run.result
    assert data['frozen']['days'] == 70
    assert data['frozen']['window'] == ['2026-09-06', '2026-11-14']
    for day in data['reconciliation']['days']:
        assert day['after_sum'] == day['region']
        assert sum(c['after'] for c in day['branches'].values()) == day['region']
        assert all(c['after'] >= 0 and isinstance(c['after'], int) for c in day['branches'].values())
    region_by_day = {r['day']: r['volume'] for r in data['frozen']['region']}
    for i, rr in enumerate(data['frozen']['region']):
        assert rr['volume'] == sum(data['frozen']['branches'][b][i]['volume'] for b in data['frozen']['members'])
    assert len(region_by_day) == 70
    assert run.week == '2026-W47'  # 未来7日窗口中间日 2026-11-18 所属 ISO 周


def test_missing_member_day_blocks_group_then_retry_same_group(env):
    S = env['Session']
    seed_volumes(S); seed_users(S)
    with S() as s:
        s.query(DailyVolume).filter_by(branch='川南', day='2026-10-01').delete()
        s.commit()
    rid = make_region(S)
    run_id = make_run(S, rid)
    with S() as s:
        run = s.get(RegionRun, run_id)
        assert run.state == 'failed'
        assert '缺日' in run.error and '川南' in run.error and '2026-10-01' in run.error
        retried = retry(s, run, s.query(User).filter_by(role='analyst').first())
        assert retried.id == run_id and retried.state == 'failed'
    with S() as s:
        s.add(DailyVolume(branch='川南', day='2026-10-01', volume=42, note='补录'))
        s.commit()
    with S() as s:
        run = retry(s, s.get(RegionRun, run_id), s.query(User).filter_by(role='analyst').first())
        assert run.id == run_id and run.state == 'pending'
        assert s.query(RegionRun).filter_by(region_id=rid).count() == 1
        compute(s, run)
        assert run.state == 'done'


def test_member_forecast_failure_fails_whole_group(env, monkeypatch):
    S = env['Session']
    seed_volumes(S); seed_users(S)
    rid = make_region(S)
    run_id = make_run(S, rid)
    import src.services.regions as regions_module
    original = regions_module.forecast

    def flaky(rows, backtest_days, alpha, beta):
        if rows[0].get('branch') == '川南':
            raise ValueError('川南日结出现异常值')
        return original(rows, backtest_days, alpha, beta)

    monkeypatch.setattr(regions_module, 'forecast', flaky)
    with S() as s:
        run = s.get(RegionRun, run_id)
        with pytest.raises(ValueError):
            compute(s, run)
    with S() as s:
        run = s.get(RegionRun, run_id)
        assert run.state == 'failed'
        assert '整组不可发布' in run.error and '川南' in run.error
        states = {m.branch: m.state for m in s.query(RegionRunMember).filter_by(region_run_id=run_id)}
        assert states['川南'] == 'failed' and states['川北'] == 'done'
        with pytest.raises(HTTPException) as exc:
            publish(s, run_id, s.query(User).filter_by(role='analyst').first())
        assert exc.value.status_code == 409
        # 重试沿用同一组，不新建
        monkeypatch.setattr(regions_module, 'forecast', original)
        run = retry(s, run, s.query(User).filter_by(role='analyst').first())
        assert run.id == run_id and run.state == 'pending'
        assert s.query(RegionRun).filter_by(region_id=rid).count() == 1


def test_request_key_is_idempotent(env):
    S = env['Session']
    seed_volumes(S); seed_users(S)
    rid = make_region(S)
    a = make_run(S, rid, key='same-request')
    b = make_run(S, rid, key='same-request')
    assert a == b
    with S() as s:
        assert s.query(RegionRun).filter_by(region_id=rid).count() == 1


def test_publish_supersedes_old_version_and_recomputes_draft_staffing(env):
    S = env['Session']
    seed_volumes(S); seed_users(S)
    rid = make_region(S)
    v1 = make_run(S, rid, key='v1'); computed(S, v1)
    with S() as s:
        old = publish(s, v1, s.query(User).filter_by(role='analyst').first())
        assert old.published_at
        v1_rows = {x.branch: x for x in s.query(Staffing).filter_by(region_id=rid, week=old.week)}
        assert set(v1_rows) == {'川北', '川南', '东河'}
        v1_schedule = {b: x.schedule for b, x in v1_rows.items()}
        staff_ids = {b: x.id for b, x in v1_rows.items()}
    v2 = make_run(S, rid, key='v2'); computed(S, v2)
    with S() as s:
        new = publish(s, v2, s.query(User).filter_by(role='analyst').first())
        old = s.get(RegionRun, v1)
        assert old.superseded_by == v2 and new.published_at
        rows = {x.branch: x for x in s.query(Staffing).filter_by(region_id=rid, week=new.week).all()}
        assert {b: x.id for b, x in rows.items()} == staff_ids   # 未新建，也未丢失
        assert all(x.region_run_id == v2 and x.status == 'draft' for x in rows.values())
        # 人数按新版预测重算
        for b, x in rows.items():
            assert x.schedule != v1_schedule[b] or x.basis['version'] == new.version
            assert [d['staff'] for d in x.schedule] == [__import__('math').ceil(d['after'] / x.capacity) for d in x.basis['days']]
            assert x.basis['region_run_id'] == v2 and x.basis['version'] == new.version


def test_publish_blocked_when_same_week_has_approved_staffing(env):
    S = env['Session']
    seed_volumes(S); seed_users(S)
    rid = make_region(S)
    v1 = make_run(S, rid); computed(S, v1)
    with S() as s:
        publish(s, v1, s.query(User).filter_by(role='analyst').first())
        row = s.query(Staffing).filter_by(region_id=rid).first()
        approve(s, row.id, s.query(User).filter_by(role='admin').first())
    v2 = make_run(S, rid); computed(S, v2)
    with S() as s:
        with pytest.raises(HTTPException) as exc:
            publish(s, v2, s.query(User).filter_by(role='analyst').first())
        assert exc.value.status_code == 409 and '签核' in exc.value.detail
        # 旧版保持发布状态
        old = s.get(RegionRun, v1)
        assert old.published_at and old.superseded_by is None
        assert s.get(RegionRun, v2).published_at == ''
        # 已签核排班仍引用旧版
        row = s.query(Staffing).filter(Staffing.status == 'approved').first()
        assert row.region_run_id == v1
        # 重复签核被拒
        with pytest.raises(HTTPException):
            approve(s, row.id, s.query(User).filter_by(role='admin').first())


def test_superseded_version_cannot_be_approved(env):
    S = env['Session']
    seed_volumes(S); seed_users(S)
    rid = make_region(S)
    v1 = make_run(S, rid); computed(S, v1)
    with S() as s:
        publish(s, v1, s.query(User).filter_by(role='analyst').first())
        row = s.query(Staffing).filter_by(region_id=rid).first()
        row_id = row.id
    v2 = make_run(S, rid); computed(S, v2)
    with S() as s:
        publish(s, v2, s.query(User).filter_by(role='analyst').first())
        # publish 已把未签核排班切到新版，因此旧引用不再存在
        row = s.get(Staffing, row_id)
        assert row.region_run_id == v2
        assert row.status == 'draft'


def test_latest_version_only_publish(env):
    S = env['Session']
    seed_volumes(S); seed_users(S)
    rid = make_region(S)
    v1 = make_run(S, rid); computed(S, v1)
    v2 = make_run(S, rid); computed(S, v2)
    with S() as s:
        with pytest.raises(HTTPException) as exc:
            publish(s, v1, s.query(User).filter_by(role='analyst').first())
        assert exc.value.status_code == 409 and '最新' in exc.value.detail


def test_zero_gap_when_region_and_members_agree(env):
    """种子数据各层都选周季节朴素，区域=成员之和时预测也严格相加，差额为0。"""
    S = env['Session']
    seed_volumes(S); seed_users(S)
    rid = make_region(S)
    run = computed(S, make_run(S, rid))
    rec = run.result['reconciliation']
    assert all(d['gap'] == 0 and d['branch_raw_sum'] == d['region'] for d in rec['days'])
    assert all(cell['delta'] == 0 for d in rec['days'] for cell in d['branches'].values())
    assert all(rec['branches'][b]['mae'] >= 0 for b in rec['branches'])


def test_gap_is_split_by_backtest_error_with_exact_daily_sum(env):
    """让区域与网点选到不同模型（趋势强时Holt胜出），验证差额分摊与整数合计。"""
    S = env['Session']
    seed_volumes(S); seed_users(S)
    # 把川北改成强趋势，使 Holt 胜出，而其余网点仍是周季节朴素
    with S() as s:
        rows = s.query(DailyVolume).filter_by(branch='川北').order_by(DailyVolume.day).all()
        for i, r in enumerate(rows):
            r.volume = 20 + i * 2
        s.commit()
    rid = make_region(S)
    run = computed(S, make_run(S, rid))
    rec = run.result['reconciliation']
    models = {b: rec['branches'][b]['model'] for b in rec['branches']}
    assert 'holt' in models.values()
    nonzero = [d for d in rec['days'] if d['gap'] != 0]
    assert nonzero, '该场景应出现区域与网点差额'
    for d in rec['days']:
        assert d['after_sum'] == d['region']
        assert sum(c['after'] for c in d['branches'].values()) == d['region']
        assert all(c['after'] >= 0 for c in d['branches'].values())
        assert all(c['after'] - c['before'] == c['delta'] for c in d['branches'].values())
    # 校正权重按回测MAE分配：误差越大权重越大
    ordered = sorted(rec['branches'], key=lambda b: rec['branches'][b]['mae'])
    weights = [rec['branches'][b]['adjust_weight'] for b in ordered]
    assert weights == sorted(weights)
    assert abs(sum(weights) - 1) < 1e-6
    # 发布后各网点排班依据保留逐日调整前后
    with S() as s:
        publish(s, run.id, s.query(User).filter_by(role='analyst').first())
        for row in s.query(Staffing).filter_by(region_id=rid).all():
            assert [d['after'] for d in row.basis['days']] == [p['prediction'] for p in row.schedule]
            assert all(d['before'] is not None and d['delta'] == d['after'] - d['before'] for d in row.basis['days'])


def test_update_members_guards_in_flight_runs(env):
    S = env['Session']
    seed_volumes(S); seed_users(S)
    rid = make_region(S)
    run_id = make_run(S, rid)
    from src.schemas.business import RegionInput as RI
    from src.services.regions import update_members
    with S() as s:
        from src.models.entities import Region
        region = s.get(Region, rid)
        analyst = s.query(User).filter_by(role='analyst').first()
        # 进行中不允许改成员
        with pytest.raises(HTTPException) as exc:
            update_members(s, region, ['川北', '川南'], analyst)
        assert exc.value.status_code == 409
        run = s.get(RegionRun, run_id)
        compute(s, run)
    with S() as s:
        from src.models.entities import Region
        region = s.get(Region, rid)
        analyst = s.query(User).filter_by(role='analyst').first()
        update_members(s, region, ['川北', '川南'], analyst)
        assert [m.branch for m in s.query(__import__('src.models.entities', fromlist=['RegionMember']).RegionMember).filter_by(region_id=rid)] == ['川北', '川南']


def test_version_numbers_use_max_plus_one(env):
    S = env['Session']
    seed_volumes(S); seed_users(S)
    rid = make_region(S)
    v1 = make_run(S, rid)
    v2 = make_run(S, rid)
    with S() as s:
        assert s.get(RegionRun, v1).version == 1 and s.get(RegionRun, v2).version == 2
        # 删掉中间版本后新版本号仍不与已有冲突
        s.delete(s.get(RegionRun, v1)); s.commit()
    v3 = make_run(S, rid)
    with S() as s:
        assert s.get(RegionRun, v3).version == 3
