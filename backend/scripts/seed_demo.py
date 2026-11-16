import random
from datetime import date,timedelta
from src.config.database import Base,engine,Session
from src.models.entities import User,DailyVolume,Region,RegionMember
from src.constants.enums import BRANCHES
from src.utils.security import hash_password
def seed():
 Base.metadata.create_all(engine);rng=random.Random(3109)
 with Session() as s:
  for role in ('admin','analyst','viewer'):
   email=role+'@demo.local'
   if not s.query(User).filter_by(email=email).first():s.add(User(email=email,role=role,password=hash_password('Demo123!')))
  for b,branch in enumerate(BRANCHES):
   for i in range(70):
    day=(date(2026,9,6)+timedelta(days=i)).isoformat();weekday=date.fromisoformat(day).weekday()
    if branch=='山前':volume=max(0,round(20+i*1.8+(6 if weekday<5 else -4)+rng.gauss(0,2)))
    else:volume=max(0,round(24+b*4+i*.12+(10 if weekday<5 else -8)+rng.gauss(0,3)))
    if not s.query(DailyVolume).filter_by(branch=branch,day=day).first():s.add(DailyVolume(branch=branch,day=day,volume=volume,note='栖川网点日结工单到达量'))
  for name,note,members in (('栖川城区','演示区域：四网点同选季节朴素，逐日零差额',('川北','川南','东河','西浦')),
                            ('山前片区','演示区域：山前有趋势选Holt，与区域差额需按权重分摊',('山前','湖滨'))):
   if not s.query(Region).filter_by(name=name).first():
    region=Region(name=name,note=note,created='2026-11-16T00:00:00+00:00');s.add(region);s.flush()
    for branch in members:s.add(RegionMember(region_id=region.id,branch=branch))
  s.commit();print({'users':s.query(User).count(),'volumes':s.query(DailyVolume).count(),'regions':s.query(Region).count()})
if __name__=='__main__':seed()
