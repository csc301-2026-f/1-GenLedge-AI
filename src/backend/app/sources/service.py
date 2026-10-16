"""Source inventory entrypoints for graph and application services."""

from app.agent.contracts import InventoryView
from app.common.database import Database
from .repository import InventoryRepository


class InventoryService:
    def __init__(self, repository: InventoryRepository, *, organization_id: str | None = None):
        self.repository = repository
        self.organization_id = organization_id

    def get_inventory(self, snapshot_id: str) -> InventoryView:
        return self.repository.get_inventory(snapshot_id, organization_id=self.organization_id)


def get_inventory(snapshot_id: str) -> InventoryView:
    """Trusted worker convenience API; request services should inject organization scope."""
    return InventoryService(InventoryRepository(Database())).get_inventory(snapshot_id)
