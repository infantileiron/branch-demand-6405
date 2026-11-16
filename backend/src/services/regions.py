import hashlib
import json
import math
import threading
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from src.models.entities import DailyVolume, Region, RegionMember, RegionRun, RegionRunMember, Staffing
from src.services.analysis import forecast, reconcile
from src.services.business import audit

# 发布与签核在同一进程内互斥；跨进程再由数据库行锁兜底。
_locks = {}
_locks_guard = threading.Lock()


def _region_lock(region_id):
    with _locks_guard:
        return _locks.setdefault(('region', region_id), threading.Lock())


def _now():
    return datetime.now(timezone.utc).isoformat()


def _week_start(day):
    year, week, _ = day.isocalendar()
    return f'{year}-W{week:02d}'


def dump_region(s, region):
    members = [m.branch for m in s.query(RegionMember).filter_by(region_id=region.id).order_by(RegionMember.id).all()]
    runs = s.query(RegionRun).filter_by(region_id=region.id).order_by(RegionRun.week.desc(), RegionRun.version.desc()).all()
    published = [r for r in runs if r.published_at and r.superseded_by is None]
    staffings = s.query(Staffing).filter_by(region_id=region.id).order_by(Staffing.id.desc()).all()
    return {
        'id': region.id, 'name': region.name, 'note': region.note, 'created': region.created,
        'members': members,
        'runs': [summarize_run(r) for r in runs],
        'published': [summarize_run(r) for r in published],
        'staffings': [{'id': x.id, 'branch': x.branch, 'week': x.week, 'status': x.status,
                       'region_run_id': x.region_run_id, 'capacity': x.capacity, 'model': x.model}
                      for x in staffings],
    }


def dump_staffing(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def summarize_run(row):
    return {
        'id': row.id, 'region_id': row.region_id, 'region_name': row.region_name, 'name': row.name,
        'week': row.week, 'version': row.version, 'state': row.state, 'error': row.error,
        'backtest_days': row.backtest_days, 'alpha': row.alpha, 'beta': row.beta, 'capacity': row.capacity,
        'created': row.created, 'published_at': row.published_at, 'superseded_by': row.superseded_by,
    }


def _lean_result(result):
    """详情响应去掉与冻结快照重复的历史序列，保留回测、未来预测、可信度与协调明细。"""
    if not result:
        return result
    out = {k: v for k, v in result.items() if k not in ('region', 'members')}
    region = result.get('region')
    if region:
        selected = region['selected_model']
        out['region'] = {'selected_model': selected, 'metrics': region['metrics'],
                         'future': region['future'], 'backtest': region['backtest'],
                         'checksum': region.get('checksum'), 'warning': region.get('warning')}
    members = result.get('members') or {}
    out['members'] = {
        branch: {'selected_model': r['selected_model'], 'metrics': r['metrics'],
                 'future': r['future'], 'backtest': r['backtest'], 'checksum': r.get('checksum')}
        for branch, r in members.items()
    }
    return out


def dump_run_detail(s, row):
    members = s.query(RegionRunMember).filter_by(region_run_id=row.id).order_by(RegionRunMember.id).all()
    data = summarize_run(row)
    data['members'] = [
        {'branch': m.branch, 'state': m.state, 'error': m.error,
         'selected_model': (m.result or {}).get('selected_model'),
         'metrics': (m.result or {}).get('metrics')}
        for m in members
    ]
    data['result'] = _lean_result(row.result)
    return data


def update_members(s, region, members, actor):
    members = list(dict.fromkeys(members))
    if len(members) < 2:
        raise HTTPException(422, '区域至少需要2个不同网点')
    with _region_lock(region.id):
        region = s.get(Region, region.id, with_for_update=True)
        if s.query(RegionRun).filter(RegionRun.region_id == region.id, RegionRun.state.in_(['pending', 'running'])).first():
            raise HTTPException(409, '有进行中的计算，不能改成员')
        s.query(RegionMember).filter_by(region_id=region.id).delete()
        for branch in members:
            s.add(RegionMember(region_id=region.id, branch=branch))
        s.commit()
    audit(s, actor, '调整区域成员 ' + region.name)
    return region


def create_region(s, data, actor):
    name = data.name.strip()
    if not name:
        raise HTTPException(422, '区域名称不能为空')
    members = list(dict.fromkeys(data.members))
    if len(members) < 2:
        raise HTTPException(422, '区域至少需要2个不同网点')
    if s.query(Region).filter_by(name=name).first():
        raise HTTPException(409, '区域名称已存在')
    region = Region(name=name, note=data.note, created=_now())
    s.add(region)
    try:
        s.flush()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, '区域名称已存在')
    for branch in members:
        s.add(RegionMember(region_id=region.id, branch=branch))
    s.commit()
    audit(s, actor, '新建区域 ' + region.name)
    return region


def freeze(s, region, backtest_days):
    """冻结区域成员同日期日量：取所有成员共同日期区间，任一天缺失即整组失败。"""
    members = [m.branch for m in s.query(RegionMember).filter_by(region_id=region.id).order_by(RegionMember.id).all()]
    if len(members) < 2:
        raise ValueError('区域至少需要2个网点成员')
    per_branch = {}
    spans = {}
    for branch in members:
        rows = s.query(DailyVolume).filter_by(branch=branch).order_by(DailyVolume.day).all()
        if not rows:
            raise ValueError(f'{branch} 没有任何日量，无法冻结区域成员数据')
        per_branch[branch] = {r.day: int(r.volume) for r in rows}
        spans[branch] = (rows[0].day, rows[-1].day)
    start = max(date.fromisoformat(v[0]) for v in spans.values())
    end = min(date.fromisoformat(v[1]) for v in spans.values())
    if start > end:
        raise ValueError('区域成员没有共同日期区间，请先补齐日量：' + '；'.join(f'{b} {spans[b][0]}~{spans[b][1]}' for b in members))
    window = []
    day = start
    while day <= end:
        window.append(day.isoformat())
        day += timedelta(days=1)
    missing = []
    for branch in members:
        for d in window:
            if d not in per_branch[branch]:
                missing.append(f'{branch} {d}')
    if missing:
        raise ValueError('成员缺日，不可将缺日当作零量：' + '、'.join(missing[:8]) + (' 等' if len(missing) > 8 else ''))
    if len(window) < backtest_days + 28:
        raise ValueError(f'共同日期窗口仅{len(window)}天，回测{backtest_days}天至少需要{backtest_days + 28}天')
    branches = {b: [{'branch': b, 'day': d, 'volume': per_branch[b][d]} for d in window] for b in members}
    region_rows = [{'branch': '区域', 'day': d, 'volume': sum(per_branch[b][d] for b in members)} for d in window]
    excluded = {b: {'before_start': int((start - date.fromisoformat(spans[b][0])).days),
                    'after_end': int((date.fromisoformat(spans[b][1]) - end).days)} for b in members}
    frozen = {'window': [window[0], window[-1]], 'days': len(window), 'members': members,
              'branches': branches, 'region': region_rows, 'excluded_edge_days': excluded}
    frozen['checksum'] = hashlib.sha256(json.dumps(frozen, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    # 业务周取未来7日窗口中间日所属 ISO 周：窗口从末日后一天起，若首日是周日，
    # 6/7 天落在下一个周一起的周内，标为该周才符合“下周”的业务含义。
    frozen['week'] = _week_start(end + timedelta(days=4))
    return frozen


def _fallback_week(s, region):
    members = [m.branch for m in s.query(RegionMember).filter_by(region_id=region.id).all()]
    last = None
    for b in members:
        row = s.query(DailyVolume).filter_by(branch=b).order_by(DailyVolume.day.desc()).first()
        if row and (last is None or row.day > last):
            last = row.day
    anchor = (date.fromisoformat(last) + timedelta(days=4)) if last else date.today()
    return _week_start(anchor)


def next_version(s, region_id, week, exclude=None):
    """同区域同周版本号取当前最大值+1，避免删除/换周后 count+1 撞号。"""
    from sqlalchemy import func
    query = s.query(func.max(RegionRun.version)).filter(RegionRun.region_id == region_id, RegionRun.week == week)
    if exclude is not None:
        query = query.filter(RegionRun.id != exclude)
    return (query.scalar() or 0) + 1


def create_run(s, region, data, actor):
    if not s.query(RegionMember).filter_by(region_id=region.id).first():
        raise HTTPException(409, '区域没有成员，无法计算')
    with _region_lock(region.id):
        region = s.get(Region, region.id, with_for_update=True)
        if data.request_key:
            existing = s.query(RegionRun).filter_by(region_id=region.id, request_key=data.request_key).first()
            if existing:
                return existing
        try:
            frozen = freeze(s, region, data.backtest_days)
        except ValueError as exc:
            frozen = None
            week = _fallback_week(s, region)
            fail_message = str(exc)
        else:
            week = frozen['week']
            fail_message = ''
        version = next_version(s, region.id, week)
        run = RegionRun(region_id=region.id, region_name=region.name, name=data.name or f'{region.name} {week} 区域需求',
                        week=week, version=version, backtest_days=data.backtest_days, alpha=data.alpha,
                        beta=data.beta, capacity=data.capacity, state='pending',
                        request_key=data.request_key or None, created=_now())
        run.result = {'frozen': frozen} if frozen else {'frozen': None}
        s.add(run)
        try:
            s.flush()
        except IntegrityError:
            s.rollback()
            if data.request_key:
                existing = s.query(RegionRun).filter_by(region_id=region.id, request_key=data.request_key).first()
                if existing:
                    return existing
            raise HTTPException(409, '同区域同周版本号冲突，请重试')
        members = [m.branch for m in s.query(RegionMember).filter_by(region_id=region.id).order_by(RegionMember.id).all()]
        for branch in members:
            s.add(RegionRunMember(region_run_id=run.id, branch=branch, state='pending'))
        if fail_message:
            run.state = 'failed'
            run.error = fail_message
            for m in s.query(RegionRunMember).filter_by(region_run_id=run.id).all():
                m.state = 'failed'
                m.error = fail_message
        s.commit()
    audit(s, actor, f'提交区域预测 {region.name} {week} v{version}')
    return run


def enqueue(run_id):
    import os
    import redis
    redis.Redis.from_url(os.environ['REDIS_URL']).rpush('demand:region_runs', run_id)


def compute(s, run):
    """计算区域与各网点回测、可信度及未来7日协调。任一网点失败则整组失败。"""
    frozen = (run.result or {}).get('frozen')
    run.state = 'running'
    s.commit()
    members = s.query(RegionRunMember).filter_by(region_run_id=run.id).order_by(RegionRunMember.id).all()
    if not frozen:
        run.state = 'failed'
        run.error = run.error or '缺少冻结数据，请重试'
        for m in members:
            m.state = 'failed'
            m.error = run.error
        s.commit()
        raise ValueError(run.error)
    member_results = {}
    failures = []
    for m in members:
        m.state = 'running'
    s.commit()
    for m in members:
        try:
            rows = frozen['branches'][m.branch]
            result = forecast(rows, run.backtest_days, run.alpha, run.beta)
            m.result = result
            m.state = 'done'
            m.error = ''
            member_results[m.branch] = result
        except Exception as exc:  # 单网点失败不阻断其余成员的状态记录，但整组不可发布
            m.state = 'failed'
            m.error = str(exc)
            failures.append(f'{m.branch}：{exc}')
        s.commit()
    if failures:
        run.state = 'failed'
        run.error = '网点计算失败，整组不可发布；' + '；'.join(failures)
        s.commit()
        raise ValueError(run.error)
    try:
        region_result = forecast(frozen['region'], run.backtest_days, run.alpha, run.beta)
        reconciliation = reconcile(region_result, member_results)
        for point in reconciliation['days']:
            if point['after_sum'] != point['region']:
                raise ValueError('协调结果与区域合计不一致')
    except Exception as exc:
        run.state = 'failed'
        run.error = f'区域汇总计算失败，整组不可发布；{exc}'
        s.commit()
        raise ValueError(run.error)
    run.result = {'frozen': frozen, 'region': region_result, 'members': {b: r for b, r in member_results.items()},
                  'reconciliation': reconciliation,
                  'warning': '区域与网点分别回测后，以区域逐日预测为总量锚点；网点独立选模结果与区域差额按各网点入选模型回测MAE分摊，误差越大承担越多校正。结果均为非负整数且每日网点合计等于区域。回测误差只用于可信度排序，不代表独立泛化精度。'}
    run.state = 'done'
    run.error = ''
    s.commit()
    return run.result


def retry(s, run, actor):
    if run.state != 'failed':
        raise HTTPException(409, '只有失败的组可以重试')
    with _region_lock(run.region_id):
        run = s.get(RegionRun, run.id, with_for_update=True)
        if run.state != 'failed':
            raise HTTPException(409, '该组已被其他请求重试')
        region = s.get(Region, run.region_id, with_for_update=True)
        member_rows = s.query(RegionRunMember).filter_by(region_run_id=run.id).all()
        try:
            frozen = freeze(s, region, run.backtest_days)
            error = ''
        except ValueError as exc:
            frozen = None
            error = str(exc)
        if frozen and frozen['week'] != run.week:
            # 补录后业务周变化：仍复用同一组，只在新周取新的版本号，避免与旧周版本冲突
            run.week = frozen['week']
            run.version = next_version(s, run.region_id, run.week, exclude=run.id)
        run.result = {'frozen': frozen}
        for m in member_rows:
            m.state = 'pending' if frozen else 'failed'
            m.error = '' if frozen else error
            m.result = None
        if frozen:
            run.state = 'pending'
            run.error = ''
        else:
            run.state = 'failed'
            run.error = error
        s.commit()
    if run.state == 'pending':
        enqueue(run.id)
    audit(s, actor, f'重试区域预测 #{run.id} v{run.version}')
    return run


def _branch_basis(run, branch, capacity):
    reconciliation = run.result['reconciliation']
    info = reconciliation['branches'][branch]
    days = []
    for point in reconciliation['days']:
        cell = point['branches'][branch]
        days.append({'day': point['day'], 'region': point['region'], 'before': cell['before'],
                     'after': cell['after'], 'delta': cell['delta'], 'correction': cell['correction'],
                     'staff': math.ceil(cell['after'] / capacity)})
    return {'region_run_id': run.id, 'region_id': run.region_id, 'week': run.week, 'version': run.version,
            'branch': branch, 'model': info['model'], 'mae': info['mae'], 'mape': info['mape'],
            'credibility': info['credibility'], 'adjust_weight': info['adjust_weight'],
            'capacity': capacity, 'days': days,
            'rule': reconciliation['rule']}


def _schedule(basis):
    return [{'day': d['day'], 'prediction': d['after'], 'before': d['before'], 'staff': d['staff']} for d in basis['days']]


def publish(s, run_id, actor):
    run = s.get(RegionRun, run_id)
    if not run:
        raise HTTPException(404, '区域预测版本不存在')
    region_id = run.region_id
    with _region_lock(region_id):
        try:
            s.get(Region, region_id, with_for_update=True)
            run = s.get(RegionRun, run_id, with_for_update=True)
            if run.state != 'done' or not run.result or 'reconciliation' not in run.result:
                raise HTTPException(409, '区域预测尚未计算成功，不能发布')
            if run.published_at:
                raise HTTPException(409, '该版本已发布，不能重复发布')
            if run.superseded_by is not None:
                raise HTTPException(409, '该版本已被替换，不能发布')
            newer = s.query(RegionRun).filter(RegionRun.region_id == region_id, RegionRun.week == run.week,
                                              RegionRun.version > run.version, RegionRun.state == 'done').count()
            if newer:
                raise HTTPException(409, '存在更新的成功版本，请发布最新版而不是回退旧版')
            # 阻止替换已签核排班：同区域同周有 approved 记录时整次发布失败，旧版保持发布态
            approved = s.query(Staffing).filter(Staffing.region_id == region_id, Staffing.week == run.week,
                                                Staffing.status == 'approved').with_for_update().all()
            if approved:
                raise HTTPException(409, '同区域同周已有签核排班，不能替换旧版；请先处理签核记录')
            current = s.query(RegionRun).filter(RegionRun.region_id == region_id, RegionRun.week == run.week,
                                                RegionRun.published_at != '',
                                                RegionRun.superseded_by.is_(None)).with_for_update().all()
            drafts = s.query(Staffing).filter(Staffing.region_id == region_id, Staffing.week == run.week,
                                              Staffing.status == 'draft').with_for_update().all()
            members = [m.branch for m in s.query(RegionMember).filter_by(region_id=region_id).order_by(RegionMember.id).all()]
            member_states = {m.branch: m.state for m in s.query(RegionRunMember).filter_by(region_run_id=run.id).all()}
            reconciled = set(run.result['reconciliation']['branches'])
            if reconciled != set(members):
                raise HTTPException(409, '区域成员在该版本计算后已调整，请重新提交计算再发布')
            if set(members) - set(member_states) or any(member_states[b] != 'done' for b in members if b in member_states):
                raise HTTPException(409, '该版本存在未成功或缺失的网点，整组不能发布')
            existing = {x.branch: x for x in drafts}
            # 已退出区域的网点：未签核草稿随版本替换一并清理，避免留下引用旧版的排班
            for row in drafts:
                if row.branch not in members:
                    s.delete(row)
            for branch in members:
                row = existing.get(branch)
                capacity = row.capacity if row and row.capacity else run.capacity
                basis = _branch_basis(run, branch, capacity)
                if row:
                    # 未签核排班整体切到新版：记录、模型、逐日人数和依据一起替换
                    row.region_run_id = run.id
                    row.branch = branch
                    row.week = run.week
                    row.capacity = capacity
                    row.model = basis['model']
                    row.schedule = _schedule(basis)
                    row.basis = basis
                else:
                    s.add(Staffing(region_id=region_id, region_run_id=run.id, branch=branch, week=run.week,
                                   capacity=capacity, model=basis['model'], schedule=_schedule(basis),
                                   note=f'{run.region_name} {run.week} 区域协调排班参考', status='draft', basis=basis))
            for old in current:
                old.superseded_by = run.id
            run.published_at = _now()
            s.commit()
        except Exception:
            s.rollback()
            raise
    audit(s, actor, f'发布区域预测 #{run.id} {run.region_name} {run.week} v{run.version}')
    return run


def approve(s, staffing_id, actor):
    row = s.get(Staffing, staffing_id)
    if not row:
        raise HTTPException(404, '排班建议不存在')
    lock_key = row.region_id or f'staffing-{staffing_id}'
    with _region_lock(lock_key):
        try:
            if row.region_id:
                s.get(Region, row.region_id, with_for_update=True)
            row = s.get(Staffing, staffing_id, with_for_update=True)
            if row.status != 'draft':
                raise HTTPException(409, '不可重复签核')
            if row.region_run_id is not None:
                version = s.get(RegionRun, row.region_run_id)
                if not version or not version.published_at or version.superseded_by is not None:
                    raise HTTPException(409, '排班引用的区域版本已被替换，请刷新后使用当前发布版')
            row.status = 'approved'
            s.commit()
        except Exception:
            s.rollback()
            raise
    audit(s, actor, f'签核排班 #{staffing_id}')
    return row
