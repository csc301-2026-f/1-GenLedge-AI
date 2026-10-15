"""Publish discovered metadata through the shared inventory repository."""

from collections.abc import Callable
from typing import Literal

from app.agent.contracts import InventoryView
from .discovery import DiscoveryResult
from .inventory_adapter import to_inventory
from .repository import InventoryRepository


def publish_discovery(result: DiscoveryResult, repository: InventoryRepository, *,
                      prepare_inventory: Callable[[InventoryView], InventoryView],
                      organization_id: str, source_id: str, source_name: str,
                      snapshot_id: str, resource_id: str, resource_name: str,
                      resource_kind: Literal["collection", "table", "sheet", "file"]) -> InventoryView:
    """Prepare one resource and return its published, possibly deduplicated snapshot.

    The caller supplies authorized identity and an explicit sample/exposure policy.
    Keep the discovery report separately for sampling metadata absent from inventory.
    """
    inventory = to_inventory(
        result, snapshot_id=snapshot_id, source_id=source_id,
        resource_id=resource_id, resource_name=resource_name,
        resource_kind=resource_kind,
    )
    prepared = prepare_inventory(inventory)
    return repository.save_snapshot(
        prepared, source_id=source_id, organization_id=organization_id,
        source_name=source_name,
    )
