import os,time,json,logging
from pathlib import Path
import redis
from src.config.database import Session
from src.models.entities import ForecastRun,RegionRun
from src.services.analysis import forecast
from src.services.regions import compute
r=redis.Redis.from_url(os.environ['REDIS_URL'])
with Session() as recovery:
 for pending in recovery.query(ForecastRun).filter(ForecastRun.state.in_(['queued','running'])).all():
  pending.state='queued';r.rpush('demand:runs',pending.id)
 for pending in recovery.query(RegionRun).filter(RegionRun.state.in_(['pending','running'])).all():
  pending.state='pending';r.rpush('demand:region_runs',pending.id)
 recovery.commit()
while True:
 Path('/tmp/heartbeat').touch()
 try:
  item=r.blpop(['demand:region_runs','demand:runs'],timeout=3)
  if not item:continue
  queue,raw=item
  if queue==b'demand:region_runs':
   with Session() as s:
    row=s.get(RegionRun,int(raw))
    if not row or row.state!='pending':continue
    try:compute(s,row)
    except Exception as e:
     logging.exception('region run %s failed',raw)
     row=s.get(RegionRun,int(raw))
     if row and row.state!='done':row.state='failed';row.error=row.error or str(e);s.commit()
   continue
  with Session() as s:
   row=s.get(ForecastRun,int(raw))
   if not row or row.state!='queued':continue
   snapshot=row.result['snapshot'];row.state='running';s.commit()
   try:
    row.result={**forecast(snapshot,row.backtest_days,row.alpha,row.beta),'snapshot':snapshot};row.state='done'
    Path('/artifacts/'+str(row.id)+'.json').write_text(json.dumps(row.result,ensure_ascii=False))
   except Exception as e:row.state='failed';row.error=str(e)
   s.commit()
 except Exception:logging.exception('worker');time.sleep(2)
