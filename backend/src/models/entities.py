from sqlalchemy import Column,Integer,String,Float,JSON,Text,ForeignKey,UniqueConstraint
from src.config.database import Base
class User(Base):
 __tablename__='users'
 id=Column(Integer,primary_key=True);email=Column(String(100),unique=True);password=Column(String(200));role=Column(String(20))
class DailyVolume(Base):
 __tablename__='daily_volumes';__table_args__=(UniqueConstraint('branch','day',name='uq_branch_day'),)
 id=Column(Integer,primary_key=True);branch=Column(String(30),nullable=False);day=Column(String(10),nullable=False);volume=Column(Integer,nullable=False);note=Column(Text,default='')
class ForecastRun(Base):
 __tablename__='forecast_runs'
 id=Column(Integer,primary_key=True);name=Column(String(100));branch=Column(String(30));backtest_days=Column(Integer);alpha=Column(Float);beta=Column(Float);state=Column(String(20),default='queued');result=Column(JSON);error=Column(Text,default='')
class Region(Base):
 __tablename__='regions'
 id=Column(Integer,primary_key=True);name=Column(String(60),unique=True,nullable=False);note=Column(Text,default='');created=Column(String(40))
class RegionMember(Base):
 __tablename__='region_members';__table_args__=(UniqueConstraint('region_id','branch',name='uq_region_branch'),)
 id=Column(Integer,primary_key=True);region_id=Column(Integer,ForeignKey('regions.id'),nullable=False);branch=Column(String(30),nullable=False)
class RegionRun(Base):
 __tablename__='region_runs';__table_args__=(UniqueConstraint('region_id','week','version',name='uq_region_week_version'),UniqueConstraint('region_id','request_key',name='uq_region_request_key'))
 id=Column(Integer,primary_key=True);region_id=Column(Integer,ForeignKey('regions.id'),nullable=False);region_name=Column(String(60));name=Column(String(100));week=Column(String(10),nullable=False);version=Column(Integer,nullable=False);backtest_days=Column(Integer);alpha=Column(Float);beta=Column(Float);capacity=Column(Integer);state=Column(String(20),default='pending');result=Column(JSON);error=Column(Text,default='');request_key=Column(String(80),nullable=True);created=Column(String(40));published_at=Column(String(40),default='');superseded_by=Column(Integer,nullable=True)
class RegionRunMember(Base):
 __tablename__='region_run_members';__table_args__=(UniqueConstraint('region_run_id','branch',name='uq_region_run_branch'),)
 id=Column(Integer,primary_key=True);region_run_id=Column(Integer,ForeignKey('region_runs.id'),nullable=False);branch=Column(String(30),nullable=False);state=Column(String(20),default='pending');result=Column(JSON);error=Column(Text,default='')
class Staffing(Base):
 __tablename__='staffings';__table_args__=(UniqueConstraint('region_id','week','branch',name='uq_region_week_branch'),)
 id=Column(Integer,primary_key=True);run_id=Column(Integer,ForeignKey('forecast_runs.id'));region_id=Column(Integer,ForeignKey('regions.id'),nullable=True);region_run_id=Column(Integer,ForeignKey('region_runs.id'),nullable=True);branch=Column(String(30),nullable=True);week=Column(String(10),nullable=True);capacity=Column(Integer);model=Column(String(30));schedule=Column(JSON);note=Column(Text);status=Column(String(20),default='draft');basis=Column(JSON)
class Audit(Base):
 __tablename__='audits'
 id=Column(Integer,primary_key=True);actor=Column(String(100));action=Column(String(200));created=Column(String(40))
