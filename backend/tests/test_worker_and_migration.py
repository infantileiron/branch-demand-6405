import sqlite3

from sqlalchemy import create_engine, inspect, text

from src.config.database import migrate_staffing_columns


def test_migration_adds_staffing_columns_to_legacy_table(tmp_path):
    path = tmp_path / 'legacy.db'
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE staffings (id INTEGER PRIMARY KEY, run_id INTEGER, capacity INTEGER, model VARCHAR(30), schedule JSON, note TEXT, status VARCHAR(20))')
    con.commit(); con.close()
    engine = create_engine(f'sqlite:///{path}')
    migrate_staffing_columns(engine)
    cols = {c['name'] for c in inspect(engine).get_columns('staffings')}
    assert {'region_id', 'region_run_id', 'branch', 'week', 'basis'} <= cols
    # 幂等：再跑一次不报错
    migrate_staffing_columns(engine)
