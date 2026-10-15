"""Deterministic synthetic discovery metadata, with no full source records."""

from app.agent.contracts import FieldRef, InventoryField, InventoryView, ResourceSummary
from app.common.database import Database
from .repository import InventoryRepository

DEMO_SOURCE_ID = "demo-orders-source"
DEMO_SNAPSHOT_ID = "demo-orders-snapshot-v1"
DEMO_ORGANIZATION_ID = "demo-organization"


def demo_inventory() -> InventoryView:
    fields = []

    def add(resource, path, kind, samples, description, *, nullable=False,
            repeating=False, native_type="string", ambiguity=None):
        fields.append(InventoryField(
            ref=FieldRef(source_id=DEMO_SOURCE_ID, resource_id=resource, field_path=path),
            type=kind, nullable=nullable, repeating=repeating, samples=samples,
            description=description, native_type=native_type, ambiguity=ambiguity, status="stable"))

    add("orders", "order_id", "text", ["ORD-1001", "ORD-1002", "ORD-1003"], "Synthetic order identifier")
    add("orders", "customer_id", "text", ["CUS-101", "CUS-102"], "Reference to the customer placing the order")
    add("orders", "order_date", "date", ["03/04/2026", "04/05/2026"], "Order date in an unspecified locale",
        ambiguity="date_format_ambiguous: DD/MM/YYYY or MM/DD/YYYY")
    add("orders", "total", "number", ["120.50", "39.00", "75.25"], "Total order amount", native_type="decimal128")
    add("orders", "tags[]", "text", ["priority", "gift"], "Optional order labels", nullable=True, repeating=True,
        native_type="array<string>")
    add("orders", "shipping_address.city", "text", ["Toronto", "Ottawa"], "Shipping city", nullable=True)
    add("orders", "shipping_address.zip", "text", [], "Shipping postal code; samples withheld", nullable=True)
    add("orders", "lines[]", "json", [], "Nested order lines; see orders.lines[]", repeating=True, native_type="array<object>")
    add("orders.lines[]", "order_id", "text", ["ORD-1001", "ORD-1002"], "Parent order reference", repeating=True)
    add("orders.lines[]", "line_id", "number", ["1", "2", "3"], "Line number within an order", repeating=True, native_type="int32")
    add("orders.lines[]", "sku", "text", ["SKU-A", "SKU-B", "SKU-C"], "Synthetic product reference", repeating=True)
    add("orders.lines[]", "quantity", "number", ["1", "2"], "Units ordered", repeating=True, native_type="int32")
    add("orders.lines[]", "unit_price", "number", ["40.00", "39.00"], "Amount per unit", repeating=True, native_type="decimal128")
    add("orders.lines[]", "discount", "number", ["0.00", "5.00"], "Optional line discount", nullable=True,
        repeating=True, native_type="decimal128")
    add("customers", "customer_id", "text", ["CUS-101", "CUS-102"], "Synthetic customer identifier", native_type="csv:string")
    add("customers", "name", "text", ["Sample Customer A", "Sample Customer B"], "Synthetic display name", native_type="csv:string")
    add("customers", "email", "text", [], "Contact email; samples withheld", nullable=True, native_type="csv:string")
    add("customers", "active", "boolean", ["true", "false"], "Whether the customer is active", native_type="csv:boolean")
    resources = [ResourceSummary(resource_id=name, name=name, kind="file" if name == "customers" else "collection",
                                 field_count=sum(field.ref.resource_id == name for field in fields))
                 for name in ("orders", "orders.lines[]", "customers")]
    return InventoryView(snapshot_id=DEMO_SNAPSHOT_ID, resources=resources, fields=fields)


def seed_demo(repository: InventoryRepository) -> InventoryView:
    return repository.save_snapshot(demo_inventory(), source_id=DEMO_SOURCE_ID,
                                    organization_id=DEMO_ORGANIZATION_ID, source_name="Synthetic orders and customers")


if __name__ == "__main__":
    print(seed_demo(InventoryRepository(Database())).snapshot_id)
