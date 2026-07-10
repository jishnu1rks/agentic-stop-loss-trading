import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app import models  # noqa: F401 - register models on Base
import app.adapters.broker as broker_module
from app.adapters.broker.simulator import SimulatorBrokerAdapter


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def fresh_broker():
    """Each test gets an isolated simulator so GTT state doesn't leak across tests."""
    broker_module._instance = SimulatorBrokerAdapter()
    yield broker_module._instance
    broker_module._instance = None
