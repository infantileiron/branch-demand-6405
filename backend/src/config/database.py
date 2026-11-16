import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
engine=create_engine(os.environ['DATABASE_URL'],pool_pre_ping=True)
Session=sessionmaker(bind=engine,expire_on_commit=False)
Base=declarative_base()
def db():
 with Session() as s: yield s

_ADDED_STAFFING_COLUMNS={
 'region_id':'INTEGER REFERENCES regions(id)',
 'region_run_id':'INTEGER REFERENCES region_runs(id)',
 'branch':'VARCHAR(30)',
 'week':'VARCHAR(10)',
 'basis':'JSON',
}
def migrate_staffing_columns(engine):
 """旧库升级：staffings 已有表时补上区域协调列与唯一约束。create_all 不会改已存在的表。"""
 from sqlalchemy import inspect,text
 inspector=inspect(engine)
 columns={c['name'] for c in inspector.get_columns('staffings')}
 if not columns:return
 with engine.begin() as c:
  for name,ddl in _ADDED_STAFFING_COLUMNS.items():
   if name not in columns:c.execute(text(f'ALTER TABLE staffings ADD COLUMN {name} {ddl}'))
  existing={u['name'] for u in inspector.get_unique_constraints('staffings')}
  if 'uq_region_week_branch' not in existing:
   try:c.execute(text('ALTER TABLE staffings ADD CONSTRAINT uq_region_week_branch UNIQUE (region_id, week, branch)'))
   except Exception:pass
