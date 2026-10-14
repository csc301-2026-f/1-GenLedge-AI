"""Repository protocols and the in-memory doubles Person B develops against.

Person A owns the PostgreSQL control schema and the real adapters. Person B needs
four reads and one write from it, so those five operations are declared here as a
`Protocol`; the concrete database implementation arrives on `us4/integration`
without this package changing.

`InMemoryRoutingRepository` is the Gate 1 fake boundary from
`plans/us4-four-person-task-split.md` and carries the seeded synthetic orders
fixture (requirement: `orders`, `orders.lines[]`, `customers`, an ambiguous
`orders.order_date`, ≤3 samples per field, and no raw rows).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from app.agent.contracts import (
    AgentBudgets,
    FieldRef,
    InventoryField,
    InventoryView,
    ResourceSummary,
    StrictModel,
    ToolResultRef,
)
from app.agent.tools import ToolResult

SOURCE_ID = "source-orders-1"
SNAPSHOT_ID = "snapshot-orders-1"
ORDERS = "orders"
ORDER_LINES = "orders.lines[]"
CUSTOMERS = "customers"


class CatalogueColumn(StrictModel):
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)


class CatalogueTable(StrictModel):
    table_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    columns: list[CatalogueColumn] = Field(default_factory=list)


class CatalogueView(StrictModel):
    """A projection of an existing warehouse catalogue: names and types only.

    The catalogue is the optional graph input behind US4-AC3's reuse path. It
    carries no rows, no owners and no warehouse connection details, so nothing in
    it needs redacting before it reaches a prompt.
    """

    catalog_ref: str = Field(min_length=1)
    tables: list[CatalogueTable] = Field(default_factory=list)


@runtime_checkable
class RoutingRepository(Protocol):
    """The persisted boundary the graph reads and writes."""

    def create_job(
        self,
        job_id: str,
        *,
        source_snapshot_ids: list[str],
        catalogue_ref: str | None = None,
    ) -> None:
        """Register the job before the first node runs."""

    def get_inventory(self, snapshot_id: str) -> InventoryView | None:
        """Load the frozen inventory for a snapshot, or `None` when unknown."""

    def get_catalogue(self, catalog_ref: str | None) -> CatalogueView | None:
        """Load the optional catalogue projection; `None` means cold start."""

    def record_tool_result(self, result: ToolResult) -> ToolResultRef:
        """Persist a redacted tool result and return its compact reference."""

    def get_tool_result(self, job_id: str, tool_call_id: str) -> ToolResult | None:
        """Fetch a recorded result for `(job_id, tool_call_id)`, or `None`."""

    def record_model_call(self, job_id: str, *, node: str, tokens: int) -> None:
        """Record one provider call. The row count is the model budget's authority."""

    def get_model_call_count(self, job_id: str) -> int:
        """Durable model-call count for a job (authority across a crash)."""


class InMemoryRoutingRepository:
    """A deterministic in-process `RoutingRepository` for tests and the fake path."""

    def __init__(
        self,
        *,
        inventories: dict[str, InventoryView] | None = None,
        catalogues: dict[str, CatalogueView] | None = None,
        model_call_counts: dict[str, int] | None = None,
    ) -> None:
        self.inventories = dict(inventories or {})
        self.catalogues = dict(catalogues or {})
        self.model_call_counts = dict(model_call_counts or {})
        self.tool_results: dict[tuple[str, str], ToolResult] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.record_calls = 0

    def create_job(
        self,
        job_id: str,
        *,
        source_snapshot_ids: list[str],
        catalogue_ref: str | None = None,
    ) -> None:
        self.jobs[job_id] = {
            "source_snapshot_ids": list(source_snapshot_ids),
            "catalogue_ref": catalogue_ref,
        }
        self.model_call_counts.setdefault(job_id, 0)

    def get_inventory(self, snapshot_id: str) -> InventoryView | None:
        return self.inventories.get(snapshot_id)

    def get_catalogue(self, catalog_ref: str | None) -> CatalogueView | None:
        if not catalog_ref:
            return None
        return self.catalogues.get(catalog_ref)

    def record_tool_result(self, result: ToolResult) -> ToolResultRef:
        self.record_calls += 1
        self.tool_results[(result.job_id, result.tool_call_id)] = result
        return result.to_ref()

    def get_tool_result(self, job_id: str, tool_call_id: str) -> ToolResult | None:
        return self.tool_results.get((job_id, tool_call_id))

    def record_model_call(self, job_id: str, *, node: str, tokens: int) -> None:
        del node, tokens
        self.model_call_counts[job_id] = self.model_call_counts.get(job_id, 0) + 1

    def get_model_call_count(self, job_id: str) -> int:
        return self.model_call_counts.get(job_id, 0)


def _field(
    *,
    field_path: str,
    type: str,
    nullable: bool,
    repeating: bool,
    samples: list[str],
    status: str = "stable",
    ambiguity: str | None = None,
    native_type: str | None = None,
    description: str | None = None,
    resource_id: str = ORDERS,
) -> InventoryField:
    return InventoryField(
        ref=FieldRef(source_id=SOURCE_ID, resource_id=resource_id, field_path=field_path),
        type=type,
        nullable=nullable,
        repeating=repeating,
        samples=samples[:3],
        description=description,
        ambiguity=ambiguity,
        status=status,
        native_type=native_type,
    )


def seeded_inventory() -> InventoryView:
    """The frozen synthetic orders fixture (`D2-PF-2`) as an `InventoryView`."""

    fields = [
        _field(field_path="order_id", type="text", nullable=False, repeating=False, samples=["O-1001", "O-1002"], description="Source order identifier."),
        _field(field_path="customer_id", type="text", nullable=False, repeating=False, samples=["C-77", "C-78"]),
        _field(
            field_path="order_date",
            type="date",
            nullable=True,
            repeating=False,
            samples=["03/04/2026", "11/12/2026"],
            ambiguity="date_format_ambiguous",
            native_type="varchar(10)",
        ),
        _field(field_path="total", type="number", nullable=True, repeating=False, samples=["120.50", "89.99"], native_type="numeric(12,2)"),
        _field(field_path="lines[]", type="json", nullable=True, repeating=True, samples=[], status="new", native_type="array"),
        _field(field_path="lines[].line_id", type="text", nullable=False, repeating=True, samples=["1", "2"], resource_id=ORDER_LINES),
        _field(field_path="lines[].sku", type="text", nullable=True, repeating=True, samples=["SKU-1", "SKU-2"], resource_id=ORDER_LINES),
        _field(field_path="lines[].quantity", type="number", nullable=True, repeating=True, samples=["2", "5"], resource_id=ORDER_LINES),
        _field(field_path="lines[].unit_price", type="number", nullable=True, repeating=True, samples=["10.25", "6.00"], resource_id=ORDER_LINES),
        _field(field_path="customer_id", type="text", nullable=False, repeating=False, samples=["C-77", "C-78"], resource_id=CUSTOMERS),
        _field(field_path="name", type="text", nullable=True, repeating=False, samples=["Ada L.", "Grace H."], description="Customer display name.", resource_id=CUSTOMERS),
        _field(field_path="email", type="text", nullable=True, repeating=False, samples=["ada@example.com"], resource_id=CUSTOMERS),
        _field(field_path="signup_date", type="timestamp", nullable=True, repeating=False, samples=["2025-01-04T09:00:00Z"], resource_id=CUSTOMERS),
    ]
    resources = [
        ResourceSummary(resource_id=ORDERS, name="orders", kind="collection", field_count=5),
        ResourceSummary(resource_id=ORDER_LINES, name="orders.lines[]", kind="collection", field_count=4),
        ResourceSummary(resource_id=CUSTOMERS, name="customers", kind="collection", field_count=4),
    ]
    return InventoryView(snapshot_id=SNAPSHOT_ID, resources=resources, fields=fields)


def seeded_catalogue() -> CatalogueView:
    """The optional existing catalogue used by the US4-AC3 reuse path."""

    return CatalogueView(
        catalog_ref="catalog-warehouse-1",
        tables=[
            CatalogueTable(
                table_id="fact_orders",
                name="fact_orders",
                columns=[
                    CatalogueColumn(name="order_id", type="text"),
                    CatalogueColumn(name="order_date", type="date"),
                    CatalogueColumn(name="total", type="number"),
                ],
            ),
            CatalogueTable(
                table_id="dim_customers",
                name="dim_customers",
                columns=[
                    CatalogueColumn(name="customer_id", type="text"),
                    CatalogueColumn(name="name", type="text"),
                ],
            ),
        ],
    )


def seeded_repository(
    *,
    with_catalogue: bool = False,
    model_call_counts: dict[str, int] | None = None,
) -> InMemoryRoutingRepository:
    """A repository holding the seeded inventory and, optionally, the catalogue."""

    catalogues: dict[str, CatalogueView] = {}
    if with_catalogue:
        catalogue = seeded_catalogue()
        catalogues[catalogue.catalog_ref] = catalogue
    return InMemoryRoutingRepository(
        inventories={SNAPSHOT_ID: seeded_inventory()},
        catalogues=catalogues,
        model_call_counts=model_call_counts,
    )


def empty_inventory_repository() -> InMemoryRoutingRepository:
    """A repository whose snapshot has no fields — the `context` failure case."""

    return InMemoryRoutingRepository(
        inventories={
            SNAPSHOT_ID: InventoryView(snapshot_id=SNAPSHOT_ID, resources=[], fields=[])
        }
    )


def budget_defaults() -> AgentBudgets:
    """A fresh frozen budget object with the documented defaults."""

    return AgentBudgets()


__all__ = [
    "CUSTOMERS",
    "ORDERS",
    "ORDER_LINES",
    "SNAPSHOT_ID",
    "SOURCE_ID",
    "CatalogueColumn",
    "CatalogueTable",
    "CatalogueView",
    "InMemoryRoutingRepository",
    "RoutingRepository",
    "budget_defaults",
    "empty_inventory_repository",
    "seeded_catalogue",
    "seeded_inventory",
    "seeded_repository",
]
