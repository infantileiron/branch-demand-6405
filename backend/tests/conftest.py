import os
import sys
from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['JWT_SECRET'] = 'test-secret'
os.environ['REDIS_URL'] = 'redis://localhost:6379/0'
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['SEED_DEMO'] = 'false'

from src.config import database
from src.models.entities import Base


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                           poolclass=__import__('sqlalchemy.pool', fromlist=['StaticPool']).StaticPool)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, 'engine', engine)
    monkeypatch.setattr(database, 'Session', Session)

    import src.main as main
    import src.routes.api as api
    import src.services.regions as regions
    monkeypatch.setattr(main, 'engine', engine)
    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(regions, 'enqueue', lambda run_id: fake.rpush('demand:region_runs', run_id))
    monkeypatch.setattr(api, 'enqueue', lambda run_id: fake.rpush('demand:region_runs', run_id))
    client = TestClient(main.app)
    yield {'client': client, 'Session': Session, 'redis': fake, 'engine': engine}
