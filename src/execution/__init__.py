"""Order manager — turns signals into broker orders under the risk guards."""

from src.execution.order_manager import OrderManager, OrderOutcome

__all__ = ["OrderManager", "OrderOutcome"]
