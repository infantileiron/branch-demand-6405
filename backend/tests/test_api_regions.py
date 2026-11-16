import json
import threading
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from fastapi.testclient import TestClient

from src.constants.enums import BRANCHES
from src.models.entities import Base, DailyVolume, Region, RegionRun, Staffing, User
from src.schemas.business import RegionInput, RegionRunInput
from src.services.regions import approve, compute, create_region, create_run, publish
from src.utils.security import hash_password
import random


def login(client, email='analyst@demo.local'):
    r = client.post('/auth/login', json={'email': email, 'password': 'Demo123!'})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['token']}


@pytest.fixture()
def api(env, monkeypatch):
    S = env['Session']
    rng = random.Random(3109)
    with S() as s:
        for role in ('admin', 'analyst', 'viewer'):
            s.add(User(email=role + '@demo.local', role=role, password=hash_password('Demo123!')))
        for b, branch in enumerate(BRANCHES[:4]):
            for i in range(70):
                day = (date(2026, 9, 6) + timedelta(days=i)).isoformat()
                weekday = date.fromisoformat(day).weekday()
                volume = max(0, round(24 + b * 4 + i * .12 + (10 if weekday < 5 else -8) + rng.gauss(0, 3)))
                s.add(DailyVolume(branch=branch, day=day, volume=volume, note='test'))
        s.commit()
    c = env['client']
    client = TestClient(c.app, raise_server_exceptions=False)
    return {'client': client, 'S': S, 'headers': login(client), 'viewer': login(client, 'viewer@demo.local'),
            'admin': login(client, 'admin@demo.local'), 'redis': env['redis']}


def drain_worker(S, fake_redis):
    """用真实 worker 逻辑消费 fakeredis 队列，不启动常驻循环。"""
    import json
    while True:
        item = fake_redis.lpop('demand:region_runs')
        if not item:
            return
        with S() as s:
            run = s.get(RegionRun, int(item))
            if run and run.state == 'pending':
                compute(s, run)


def test_region_api_end_to_end(api):
    c = api['client']; h = api['headers']
    r = c.post('/regions', headers=h, json={'name': '川东片区', 'note': '演示', 'members': ['川北', '川南', '东河']})
    assert r.status_code == 200, r.text
    rid = r.json()['id']
    assert r.json()['members'] == ['川北', '川南', '东河']
    # 观察员只读
    assert c.post('/regions', headers=api['viewer'], json={'name': 'x2', 'members': ['川北', '川南']}).status_code == 403
    # 重名
    assert c.post('/regions', headers=h, json={'name': '川东片区', 'members': ['川北', '川南']}).status_code == 409
    run = c.post(f'/regions/{rid}/runs', headers=h, json={'backtest_days': 14, 'alpha': .6, 'beta': .2, 'capacity': 10})
    assert run.status_code == 200, run.text
    body = run.json()
    assert body['state'] == 'pending' and body['week'] == '2026-W47'
    # 待算状态不能发布
    assert c.post(f'/region-runs/{body["id"]}/publish', headers=h).status_code == 409
    drain_worker(api['S'], api['redis'])
    detail = c.get(f'/region-runs/{body["id"]}', headers=h).json()
    assert detail['state'] == 'done', detail
    basis = c.get(f'/region-runs/{body["id"]}/basis', headers=h).json()
    for day in basis['reconciliation']['days']:
        assert day['after_sum'] == day['region']
        assert all(cell['after'] >= 0 for cell in day['branches'].values())
    assert set(basis['reconciliation']['branches']) == {'川北', '川南', '东河'}
    pub = c.post(f'/region-runs/{body["id"]}/publish', headers=h)
    assert pub.status_code == 200, pub.text
    assert pub.json()['published_at']
    staffings = c.get('/staffings', headers=api['viewer']).json()
    assert len(staffings) == 3
    assert all(x['status'] == 'draft' and x['region_id'] == rid and x['capacity'] == 10 for x in staffings)
    # 重复发布被拒
    assert c.post(f'/region-runs/{body["id"]}/publish', headers=h).status_code == 409
    # 观察员不能发布
    assert c.post(f'/region-runs/{body["id"]}/publish', headers=api['viewer']).status_code == 403


def test_missing_member_day_api_requires_retry_same_group(api):
    c = api['client']; h = api['headers']
    rid = c.post('/regions', headers=h, json={'name': '缺日区', 'members': ['川北', '川南']}).json()['id']
    with api['S']() as s:
        s.query(DailyVolume).filter_by(branch='川南', day='2026-09-20').delete()
        s.commit()
    run = c.post(f'/regions/{rid}/runs', headers=h, json={}).json()
    assert run['state'] == 'failed' and '缺日' in run['error']
    before = c.get('/regions', headers=h).json()[0]['runs']
    assert len(before) == 1
    # 修复缺日
    assert c.post('/volumes', headers=h, json={'branch': '川南', 'day': '2026-09-20', 'volume': 30, 'note': '补录'}).status_code == 200
    retried = c.post(f'/region-runs/{run["id"]}/retry', headers=h)
    assert retried.status_code == 200, retried.text
    assert retried.json()['id'] == run['id'] and retried.json()['state'] == 'pending'
    assert len(c.get('/regions', headers=h).json()[0]['runs']) == 1
    drain_worker(api['S'], api['redis'])
    assert c.get(f'/region-runs/{run["id"]}', headers=h).json()['state'] == 'done'


def test_publish_and_approve_are_serialized(api):
    """并发发布新版与签核旧版：要么签核先成功（新版发布被拒、旧版保留），
    要么发布先成功（未签核排班全部切到新版，签核后引用新版）。不出现签核旧版。"""
    c = api['client']; h = api['headers']; S = api['S']
    rid = c.post('/regions', headers=h, json={'name': '并发区', 'members': ['川北', '川南']}).json()['id']
    v1 = c.post(f'/regions/{rid}/runs', headers=h, json={}).json()
    drain_worker(S, api['redis'])
    assert c.post(f'/region-runs/{v1["id"]}/publish', headers=h).status_code == 200
    v2 = c.post(f'/regions/{rid}/runs', headers=h, json={}).json()
    drain_worker(S, api['redis'])
    draft_ids = [x['id'] for x in c.get('/staffings', headers=h).json() if x['status'] == 'draft']
    assert len(draft_ids) == 2

    barrier = threading.Barrier(2)
    outcomes = {}

    def do_publish():
        with S() as s:
            try:
                barrier.wait()
                publish(s, v2['id'], s.query(User).filter_by(role='analyst').first())
                outcomes['publish'] = 'ok'
            except Exception as exc:
                outcomes['publish'] = getattr(exc, 'detail', str(exc))

    def do_approve():
        with S() as s:
            try:
                barrier.wait()
                approve(s, draft_ids[0], s.query(User).filter_by(role='admin').first())
                outcomes['approve'] = 'ok'
            except Exception as exc:
                outcomes['approve'] = getattr(exc, 'detail', str(exc))

    t1 = threading.Thread(target=do_publish); t2 = threading.Thread(target=do_approve)
    t1.start(); t2.start(); t1.join(); t2.join()
    won = [k for k in ('publish', 'approve') if outcomes.get(k) == 'ok']
    assert won, outcomes
    assert 'ok' in outcomes.values()
    with S() as s:
        approved = s.query(Staffing).filter_by(region_id=rid, status='approved').all()
        runs = {r.id: r for r in s.query(RegionRun).filter_by(region_id=rid).all()}
        current = [r for r in runs.values() if r.published_at and r.superseded_by is None]
        # 不留下引用被替换旧版的未签核排班
        for row in s.query(Staffing).filter_by(region_id=rid, status='draft').all():
            ref = runs.get(row.region_run_id)
            assert ref is not None and ref.superseded_by is None, '存在引用旧版的未签核排班'
        if approved:
            for row in approved:
                assert runs[row.region_run_id].published_at
        assert len(current) == 1
        if outcomes['publish'] == 'ok':
            assert current[0].id == v2['id']
            assert all(row.region_run_id == v2['id'] for row in s.query(Staffing).filter_by(region_id=rid).all())
        else:
            assert current[0].id == v1['id']
            assert '签核' in str(outcomes['publish'])


def test_publish_failure_keeps_old_version(api, monkeypatch):
    c = api['client']; h = api['headers']; S = api['S']
    rid = c.post('/regions', headers=h, json={'name': '回滚区', 'members': ['川北', '川南']}).json()['id']
    v1 = c.post(f'/regions/{rid}/runs', headers=h, json={}).json()
    drain_worker(S, api['redis'])
    assert c.post(f'/region-runs/{v1["id"]}/publish', headers=h).status_code == 200
    draft = [x for x in c.get('/staffings', headers=h).json()][0]
    v2 = c.post(f'/regions/{rid}/runs', headers=h, json={}).json()
    drain_worker(S, api['redis'])

    def boom(*a, **k):
        raise RuntimeError('模拟发布中途失败')
    monkeypatch.setattr('src.services.regions._branch_basis', boom)
    assert c.post(f'/region-runs/{v2["id"]}/publish', headers=h).status_code == 500
    with S() as s:
        old = s.get(RegionRun, v1['id'])
        new = s.get(RegionRun, v2['id'])
        assert old.published_at and old.superseded_by is None and new.published_at == ''
        row = s.get(Staffing, draft['id'])
        assert row.region_run_id == v1['id'] and row.status == 'draft'


def test_approve_rejects_draft_referencing_superseded_version(api):
    """防御性校验：若草稿仍引用已被替换的版本（例如外部写入），签核必须拒绝。"""
    c = api['client']; h = api['headers']; S = api['S']
    rid = c.post('/regions', headers=h, json={'name': '防御区', 'members': ['川北', '川南']}).json()['id']
    v1 = c.post(f'/regions/{rid}/runs', headers=h, json={}).json()
    drain_worker(S, api['redis'])
    c.post(f'/region-runs/{v1["id"]}/publish', headers=h)
    v2 = c.post(f'/regions/{rid}/runs', headers=h, json={}).json()
    drain_worker(S, api['redis'])
    c.post(f'/region-runs/{v2["id"]}/publish', headers=h)
    with S() as s:
        row = s.query(Staffing).filter_by(region_id=rid, status='draft').first()
        row.region_run_id = v1['id']
        row_id = row.id
        s.commit()
    r = c.post(f'/staffings/{row_id}/approve', headers=api['admin'])
    assert r.status_code == 409 and '替换' in r.json()['detail']


def test_publish_rejects_group_with_missing_member_result(api):
    c = api['client']; h = api['headers']; S = api['S']
    rid = c.post('/regions', headers=h, json={'name': '缺失成员区', 'members': ['川北', '川南']}).json()['id']
    v1 = c.post(f'/regions/{rid}/runs', headers=h, json={}).json()
    drain_worker(S, api['redis'])
    from src.models.entities import RegionRunMember
    with S() as s:
        m = s.query(RegionRunMember).filter_by(region_run_id=v1['id']).first()
        m.state = 'failed'
        s.commit()
    r = c.post(f'/region-runs/{v1["id"]}/publish', headers=h)
    assert r.status_code == 409 and '整组' in r.json()['detail']


def test_member_leaving_region_removes_stale_draft_on_publish(api):
    c = api['client']; h = api['headers']; S = api['S']
    rid = c.post('/regions', headers=h, json={'name': '换人区', 'members': ['川北', '川南']}).json()['id']
    v1 = c.post(f'/regions/{rid}/runs', headers=h, json={}).json()
    drain_worker(S, api['redis'])
    c.post(f'/region-runs/{v1["id"]}/publish', headers=h)
    assert len([x for x in c.get('/staffings', headers=h).json() if x['region_id'] == rid]) == 2
    assert c.put(f'/regions/{rid}/members', headers=h, json={'name': '', 'members': ['川北', '东河']}).status_code == 200
    v2 = c.post(f'/regions/{rid}/runs', headers=h, json={}).json()
    drain_worker(S, api['redis'])
    assert c.post(f'/region-runs/{v2["id"]}/publish', headers=h).status_code == 200
    rows = [x for x in c.get('/staffings', headers=h).json() if x['region_id'] == rid]
    assert {x['branch'] for x in rows} == {'川北', '东河'}


def test_detail_does_not_echo_full_frozen_history(api):
    c = api['client']; h = api['headers']; S = api['S']
    rid = c.post('/regions', headers=h, json={'name': '瘦身区', 'members': ['川北', '川南']}).json()['id']
    v = c.post(f'/regions/{rid}/runs', headers=h, json={}).json()
    drain_worker(S, api['redis'])
    body = c.get(f'/region-runs/{v["id"]}', headers=h).json()
    # 冻结的逐日原始序列仍保存在快照中，但不整包回显历史
    assert 'frozen' in body['result']
    assert 'history' not in json.dumps(body['result']['members'])
    for m in body['result']['members'].values():
        assert set(m) >= {'selected_model', 'metrics', 'future', 'backtest'}


def test_publish_after_member_change_requires_new_run(api):
    c = api['client']; h = api['headers']; S = api['S']
    rid = c.post('/regions', headers=h, json={'name': '成员变更区', 'members': ['川北', '川南']}).json()['id']
    v1 = c.post(f'/regions/{rid}/runs', headers=h, json={}).json()
    drain_worker(S, api['redis'])
    c.put(f'/regions/{rid}/members', headers=h, json={'members': ['川北', '东河']})
    r = c.post(f'/region-runs/{v1["id"]}/publish', headers=h)
    assert r.status_code == 409 and '调整' in r.json()['detail']
