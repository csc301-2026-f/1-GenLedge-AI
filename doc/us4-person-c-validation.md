# US4 routing projection and validation handoff

The worker can call `project_model_draft(model_draft, inventory, catalog_table_ids)` from `app.mappings.validation`. It returns `(mapping_draft, is_new_by_table, coverage, findings)`. `catalog_table_ids=None` is a cold start, so every table is new. The worker resolves `catalog_ref` before calling this pure function. `run_checks(model_draft, mapping_draft, inventory, coverage)` repeats the business checks for an edited or supplied mapping draft. Both functions use the frozen types in `app.agent.contracts`; the worker owns persistence and job status.

Projection creates an empty-operation mapping only when an attribute cites exactly one discovered source field. It never guesses a join, transform, or multi-field calculation. Multiple sources or an invalid reference leave the target in `unmapped_targets`. A blocked table does not remove mappings for other tables. Findings use the ten codes frozen in `FindingCode`. `partial_table_failure` is a warning on a package that contains both blocked and valid tables; the table's structural blocker remains visible.

`project_inventory(inventory, sensitive_fields)` is an allow-list for inventory context. It excludes `source_id`, resource display names, raw rows, and connector metadata; samples are capped at three and redacted. Pass canonical `resource.field` names in `sensitive_fields` to hide values whose sensitivity is known from source metadata. `redact_value` and `redact_samples` use stable category markers for email, phone, address, identifiers, credentials, and unknown sensitive values. The graph/tool owner must call redaction before persisting or rendering tool results; this module does not intercept their I/O.

## Valid example

This abbreviated input is sufficient to reproduce the projection. Every object shown is a contract-shaped JSON object; omitted optional fields take the contract defaults.

```json
{
  "inventory": {
    "snapshot_id": "snapshot-1",
    "resources": [{"resource_id": "orders", "name": "orders", "kind": "collection", "field_count": 1}],
    "fields": [{"ref": {"source_id": "source-1", "resource_id": "orders", "field_path": "order_id"}, "type": "text", "nullable": false, "repeating": false, "samples": ["<redacted:identifier>"], "status": "stable"}]
  },
  "model_draft": {
    "revision": 2,
    "tables": [{"id": "fact_orders", "name": "fact_orders", "kind": "event", "grain": "one row per order", "key": ["order_id"], "attributes": [{"id": "order_id", "type": "text", "nullable": false, "evidence": [{"resource_id": "orders", "field_path": "order_id"}], "confidence": 0.95}], "relationships": [], "rationale": "Order identifier is the observed grain."}],
    "source_coverage": [{"resource_id": "orders", "field_path": "order_id", "disposition": "represented", "reason": "Mapped to order_id"}]
  }
}
```

With no catalogue, projection returns `is_new_by_table={"fact_orders": true}`, one `Mapping(target="fact_orders.order_id", sources=["orders.order_id"], operations=[])`, one represented coverage record, and no findings.

## Invalid example

The same inventory with a model attribute whose evidence is `{"resource_id":"orders","field_path":"missing"}` produces `invalid_source_reference` (blocker) and `unmapped_target_field` (warning). Adding a valid second table preserves its mapping and adds `partial_table_failure` (warning). A caller-supplied `MappingDraft` with `based_on_model_revision=1` against model revision `2` produces `stale_mapping_revision` (blocker). Unknown JSON fields, invented operations or finding codes, type coercions, and out-of-range confidence are rejected by the strict contracts at the parsing boundary.

## Limits

`TransformOp` names are checked against the frozen twelve-member vocabulary; this slice does not compile operations or validate every operation's argument semantics. The frozen finding enum has no dedicated `multiple_repeating_expansions` code, so that US6 rule needs team review before it can have its specified distinct finding. Redaction uses deterministic heuristics and an explicit sensitive-field set; it is not a complete PII detector. No database, graph node, model adapter, route, or frontend code is part of this handoff.
