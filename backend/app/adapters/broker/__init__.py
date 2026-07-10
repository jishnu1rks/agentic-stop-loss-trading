from app.config import settings
from app.adapters.broker.base import BrokerAdapter
from app.adapters.broker.simulator import SimulatorBrokerAdapter

_instance: BrokerAdapter | None = None


def get_broker_adapter() -> BrokerAdapter:
    global _instance
    if _instance is not None:
        return _instance
    if settings.broker_provider == "simulator":
        _instance = SimulatorBrokerAdapter()
    elif settings.broker_provider == "kite":
        # Phase 2: from app.adapters.broker.kite import KiteBrokerAdapter
        raise NotImplementedError(
            "Kite broker adapter is a Phase 2 stub - not implemented yet. "
            "Set BROKER_PROVIDER=simulator."
        )
    else:
        raise ValueError(f"Unknown broker_provider: {settings.broker_provider}")
    return _instance
