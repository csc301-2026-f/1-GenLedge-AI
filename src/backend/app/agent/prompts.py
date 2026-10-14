"""Versioned prompts, the projection allow-list, and the untrusted-data wrapper.

This module is the **only** path from the process to a model prompt.
`plans/user-stories/US4.md` §5.1 states the boundary as a requirement rather than a
prompt instruction, so it is enforced by construction:

* the projection functions are typed against `InventoryView`, `CatalogueView` and
  `ToolResult` — never against the graph state, a `dict`, or `Any` — so passing a
  raw row, a connector payload or an ORM object into a prompt takes a deliberate
  type change instead of an oversight;
* the projection allow-list is exactly: snapshot id, resource ids, **names**, kinds and
  field counts, field paths, types, nullability, repeating status, at most three
  (redacted) samples per field, the ambiguity marker, the field status, and the native
  type; for the catalogue, an opaque `catalog_ref` plus table and column names and
  types. Field descriptions are deliberately **not** projected (US4 §9.2 `DC-1`);
* every source-derived string is emitted inside an `<untrusted_...>` block;
* restricted values — credentials, DSNs, connection strings, e-mail addresses —
  are redacted by the tool layer before persistence and again defensively here.

Rendering is strict: a variable declared in the front-matter that is absent from
the render map, or a placeholder with no declaration, is an error rather than a
silently empty string.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.agent.contracts import AgentBudgets, ModelDraft
from app.agent.repositories import CatalogueView
from app.agent.tools import ToolResult, merge_path, redact_payload, redact_value

PROMPTS_DIR = Path(__file__).with_name("prompts")
SCHEMA_FIELD = "output_schema"
#: Page cap for the inventory block. A larger inventory degrades deterministically
#: with an explicit marker rather than growing the prompt without bound.
MAX_PROJECTED_FIELDS = 200
MAX_PROJECTED_RESOURCES = 50
MAX_PROJECTED_TOOL_RESULTS = 5
MAX_PROJECTED_TOOL_ROWS = 3
#: Per-block character cap. A result larger than this is truncated with a marker
#: rather than growing the prompt without bound.
MAX_PROJECTED_TEXT = 4000

#: What a forged delimiter becomes. Visible, so a reviewer can see the source
#: contained one, and inert, so it cannot close the block it sits inside.
DELIMITER_MARKER = "[delimiter-removed]"
_DELIMITER_TOKENS = (
    "<untrusted_source_data>",
    "</untrusted_source_data>",
    "<untrusted_tool_data>",
    "</untrusted_tool_data>",
    "<untrusted_catalogue_data>",
    "</untrusted_catalogue_data>",
    "<previous_response>",
    "</previous_response>",
)

#: The three blocks the projection wraps. Named once so a test can assert the count is
#: exactly one open and one close each, whatever the source contains.
UNTRUSTED_BLOCKS = (
    ("<untrusted_source_data>", "</untrusted_source_data>"),
    ("<untrusted_catalogue_data>", "</untrusted_catalogue_data>"),
    ("<untrusted_tool_data>", "</untrusted_tool_data>"),
)


def neutralise_delimiters(value: Any) -> Any:
    """Stop source text from forging a prompt delimiter.

    Every delimiter in a prompt is a **fixed string the harness writes**. If a value
    the harness interpolates contains one of those strings, and that value is not
    neutralised, it closes — or opens — a block early and the text after it lands in the
    prompt's instruction region, which is exactly what the boundary exists to prevent.

    The tokens covered are all of them: the two untrusted-data blocks and the
    `previous_response` quote in the repair prompt. A model can put `</previous_response>`
    in its own answer, so that block is forgeable from the *model* side, not only the
    source side.
    """

    if isinstance(value, str):
        for token in _DELIMITER_TOKENS:
            if token in value:
                value = value.replace(token, DELIMITER_MARKER)
        return value
    if isinstance(value, (list, tuple)):
        return [neutralise_delimiters(item) for item in value]
    if isinstance(value, dict):
        return {str(key): neutralise_delimiters(item) for key, item in value.items()}
    return value


def projected(value: Any, field_path: str = "") -> Any:
    """The single chokepoint every source-derived value passes through.

    Redaction and delimiter neutralisation were applied by hand at each render site,
    and the two that were missed — `snapshot_id` and `resource_id` — were missed
    precisely because a hand-applied rule has no chokepoint. Routing everything through
    one function makes "did we forget a site?" answerable by reading one place, and
    `test_no_forgery_vector_can_close_a_block` and the per-field fuzz in
`test_prompt_boundary_fuzz.py` are what assert each site uses it.
    """

    return neutralise_delimiters(redact_value(value, field_path))



_VARIABLE = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
#: One capture group, so `re.split` yields alternating literal/name segments.
_TEMPLATE_SPLIT = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
_FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)


class PromptError(RuntimeError):
    """A prompt could not be loaded or rendered as declared."""


@dataclass(frozen=True)
class PromptSpec:
    prompt_id: str
    version: int
    variables: tuple[str, ...]
    contract: str
    template: str

    @property
    def ref(self) -> str:
        return f"{self.prompt_id}@{self.version}"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.template.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RenderedPrompt:
    """A prompt ready for a model call, with its provenance attached."""

    system: str
    user: str
    ref: str
    sha256: str

    def digest(self) -> str:
        return hashlib.sha256(f"{self.system}\n--\n{self.user}".encode("utf-8")).hexdigest()


def _parse_front_matter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    match = _FRONT_MATTER.match(text)
    if match is None:
        raise PromptError(f"{path.name} has no front-matter block")
    header: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            header.setdefault("_list", []).append(stripped[2:].strip())
            continue
        key, _, value = stripped.partition(":")
        header[key.strip()] = value.strip()
    return header, text[match.end():]


def load_prompt(prompt_id: str) -> PromptSpec:
    """Load and validate one prompt file against its own front-matter."""

    path = PROMPTS_DIR / f"{prompt_id}.md"
    if not path.is_file():
        raise PromptError(f"unknown prompt {prompt_id!r}")
    header, body = _parse_front_matter(path.read_text(encoding="utf-8"), path)
    declared = tuple(header.get("_list", ()))
    found = set(_VARIABLE.findall(body))
    declared_set = set(declared)
    missing = declared_set - found
    undeclared = found - declared_set
    if missing or undeclared:
        raise PromptError(
            f"{prompt_id}.md front-matter and placeholders disagree: "
            f"declared-but-unused={sorted(missing)} used-but-undeclared={sorted(undeclared)}"
        )
    try:
        version = int(str(header.get("version", "")))
    except ValueError as error:
        raise PromptError(f"{prompt_id}.md has a non-numeric version") from error
    return PromptSpec(
        prompt_id=str(header.get("id", prompt_id)),
        version=version,
        variables=declared,
        contract=str(header.get("contract", "none")),
        template=body,
    )


def manifest() -> dict[str, str]:
    """`id@version -> sha256` for every checked-in prompt.

    The digest is of the whole file, so a silent edit to an instruction or to the
    front-matter both show up. `prompts/manifest.json` holds the reviewed values;
    a mismatch is caught by `tests/agent/test_prompt_safety.py`.
    """

    digests: dict[str, str] = {}
    for path in sorted(PROMPTS_DIR.glob("*.md")):
        spec = load_prompt(path.stem)
        digests[spec.ref] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def render(prompt_id: str, variables: Mapping[str, Any]) -> RenderedPrompt:
    """Render a prompt strictly: every declared variable must be supplied.

    Substitution is a **single pass** over the template, so a substituted value can
    never be reinterpreted as a placeholder. Source data may legitimately contain
    `{{...}}` — sample text is untrusted and is allowed to look like anything — and a
    two-pass `str.replace` loop would both crash on it and let it splice another
    prompt block into itself. The template is split into literal and placeholder
    segments once; only the template's own placeholders are ever substituted.
    """

    spec = load_prompt(prompt_id)
    supplied = set(variables)
    declared = set(spec.variables)
    missing = declared - supplied
    extra = supplied - declared
    if missing or extra:
        raise PromptError(
            f"render map for {spec.ref} does not match its declaration: "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )
    pieces = _TEMPLATE_SPLIT.split(spec.template)
    # `re.split` with one capture group alternates literal, name, literal, name, …
    body = "".join(
        str(variables[piece]) if index % 2 else piece for index, piece in enumerate(pieces)
    )
    return RenderedPrompt(
        system=load_prompt("shared_system").template.strip(),
        user=body.strip(),
        ref=spec.ref,
        sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
    )


# --- projection allow-list -----------------------------------------------------


def _bounded(items: list[Any], limit: int, label: str) -> tuple[list[Any], str]:
    if len(items) <= limit:
        return items, ""
    return items[:limit], f"    ... and {len(items) - limit} more {label}\n"


def project_inventory(inventory: Any) -> str:
    """The model-facing inventory: one line per field, ≤3 samples, no rows.

    Every value here goes through `projected()`. The `snapshot_id`, `resource_id` and
    field path are as source-derived as a sample is — master §7.6 names "a malicious
    field path" as a threat — so they are redacted and neutralised too.
    """

    lines = [f"snapshot_id: {projected(inventory.snapshot_id, 'snapshot_id')}"]
    resources, marker = _bounded(list(inventory.resources), MAX_PROJECTED_RESOURCES, "resources")
    lines.append("resources:")
    for resource in resources:
        # The resource *name* is projected, not only its id: US4-AC6 has the model
        # reason over names, and a connector's ids are often opaque (`tbl_47`).
        lines.append(
            f"  - {projected(resource.resource_id, 'resource_id')} "
            f"(name={projected(resource.name, 'name')}, kind={resource.kind}, "
            f"fields={resource.field_count})"
        )
    if marker:
        lines.append(marker.rstrip("\n"))
    lines.append("fields:")
    fields, marker = _bounded(list(inventory.fields), MAX_PROJECTED_FIELDS, "fields")
    for field in fields:
        path = _bounded_text(projected(_field_path(field.ref.resource_id, field.ref.field_path), "field_path"))
        # A single sample is capped too: the block-level cap protects the total, this
        # protects against one pathological value (a 100k-char string) crowding out
        # every other field before the block cap is even reached. The path is the
        # field-path argument as well as the value's own name, so a field whose *name*
        # says what it holds (`customers.email`) has its samples replaced too — a
        # redaction rule that only looked at the value would still project
        # `ada@example.com` as the sample of a field called `email`.
        samples = [
            _bounded_text(projected(value, f"{field.ref.field_path} {field.ref.resource_id}"))
            for value in field.samples[:3]
        ]
        detail = [
            f"type={field.type.value if hasattr(field.type, 'value') else field.type}",
            f"nullable={field.nullable}",
            f"repeating={field.repeating}",
            f"status={field.status}",
        ]
        if field.ambiguity:
            detail.append(f"ambiguity={projected(field.ambiguity, 'ambiguity')}")
        if field.native_type:
            detail.append(f"native_type={projected(field.native_type, 'native_type')}")
        if samples:
            detail.append("samples=" + ", ".join(str(item) for item in samples))
        lines.append(f"  - {path} [{'; '.join(detail)}]")
    if marker:
        lines.append(marker.rstrip("\n"))
    return _bounded_text("\n".join(lines))


def _field_path(resource_id: str, field_path: str) -> str:
    """Render a dotted path, merging a resource and field path that already overlap.

    A repeating resource is addressed as `orders.lines[]` and its fields as
    `lines[].sku`; the model must read `orders.lines[].sku`, not
    `orders.lines[].lines[].sku`. Delegated to `tools.merge_path` so the argument
    validator and the prompt cannot disagree about what a legal path looks like — a
    naive `resource.field` join made the validator refuse the very spelling the prompt
    displays.
    """

    return merge_path(resource_id, field_path)


def project_catalogue(catalogue: CatalogueView | None) -> str:
    """Table and column names and types only, or the cold-start sentence."""

    if catalogue is None or not catalogue.tables:
        return "No existing warehouse catalogue. Propose a new model."
    lines = [f"catalog_ref: {projected(catalogue.catalog_ref, 'catalog_ref')}"]
    tables, marker = _bounded(list(catalogue.tables), MAX_PROJECTED_RESOURCES, "tables")
    for table in tables:
        columns = ", ".join(
            f"{projected(column.name, 'column')} {projected(column.type, 'type')}"
            for column in table.columns
        )
        lines.append(
            f"  - {projected(table.table_id, 'table_id')} "
            f"({projected(table.name, 'table_name')}): {columns}"
        )
    if marker:
        lines.append(marker.rstrip("\n"))
    return _bounded_text("\n".join(lines))


def project_tool_results(results: list[ToolResult]) -> str:
    """Recorded tool results, redacted again and bounded, as compact JSON.

    Successes **and** typed errors are projected. A tool error is data the model has
    to adapt to (US4 §4.2, master §5.4 boundary 3), so dropping it would leave a live
    model re-requesting blind until its budget ran out.

    The tool *name* and `tool_call_id` are projected too. The call id is
    **model-authored**, and for an unknown tool the name is whatever the model asked
    for, so both are forgeable and both pass through `projected()`.
    """

    usable = results[-MAX_PROJECTED_TOOL_RESULTS:]
    if not usable:
        return "No tool results recorded yet."
    blocks = []
    for result in usable:
        tool = projected(result.tool, "tool")
        call_id = projected(result.tool_call_id, "tool_call_id")
        if result.status == "ok":
            # The tool layer redacts before persistence. This second pass is defence
            # in depth at the boundary that actually reaches the provider, so a
            # result recorded by a buggy or older writer still cannot leak a
            # credential.
            payload = projected(_cap_rows(redact_payload(result.payload), MAX_PROJECTED_TOOL_ROWS))
            rendered = _bounded_text(json.dumps(payload, sort_keys=True, default=str))
            blocks.append(f"- {tool} (tool_call_id={call_id}): {rendered}")
            continue
        failure = {
            # `error_code` is `str | None` on an unconstrained model, so it is a
            # source-derived token like any other and goes through the same chokepoint
            # as the tool name and call id above.
            "error_code": projected(result.error_code, "error_code"),
            "message": _bounded_text(str(projected(result.message or "", "message"))),
        }
        blocks.append(
            f"- {tool} (tool_call_id={call_id}) FAILED: "
            f"{_bounded_text(json.dumps(failure, sort_keys=True))} "
            "Adapt to this result; do not repeat the same call."
        )
    return "\n".join(blocks)


def _bounded_text(text: str) -> str:
    if len(text) <= MAX_PROJECTED_TEXT:
        return text
    return text[:MAX_PROJECTED_TEXT] + f" […truncated {len(text) - MAX_PROJECTED_TEXT} chars]"


def _cap_rows(value: Any, limit: int) -> Any:
    """Cap every row list in a projected payload, at any depth.

    Capping only a top-level `rows` key would let a connector's nested row list
    through unbounded. The cap follows the data, not one expected key name.
    """

    if isinstance(value, list):
        capped = [_cap_rows(item, limit) for item in value[:limit]]
        if len(value) > limit:
            capped.append(f"… and {len(value) - limit} more rows")
        return capped
    if isinstance(value, dict):
        return {str(key): _cap_rows(item, limit) for key, item in value.items()}
    return value


def project_budgets(budgets: AgentBudgets) -> str:
    """One line per budget. No provider name, no key, no price table."""

    return "\n".join(
        [
            f"max_model_calls={budgets.max_model_calls}",
            f"max_tool_calls={budgets.max_tool_calls}",
            f"max_tokens={budgets.max_tokens}",
            f"max_tool_rows={budgets.max_tool_rows}",
            f"max_tool_bytes={budgets.max_tool_bytes}",
        ]
    )


def project_output_schema(contract: str) -> str:
    """The output schema, generated from the contract rather than hand-written."""

    if contract == "ModelDraft":
        return _schema_text(ModelDraft.model_json_schema())
    if contract == SCHEMA_FIELD:
        return _schema_text(ModelDraft.model_json_schema())
    raise PromptError(f"no schema is registered for contract {contract!r}")


def _schema_text(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True)


def job_ref(job_id: str) -> str:
    """An opaque job reference: a prefix of the id, never the organization id."""

    return job_id[:8]


def proposal_prompt_variables(
    *,
    job_id: str,
    inventory: Any,
    catalogue: CatalogueView | None,
    tool_results: list[ToolResult],
    budgets: AgentBudgets,
) -> dict[str, str]:
    """The complete render map for `propose`. Adding a key means editing its test."""

    return {
        "job_ref": job_ref(job_id),
        "inventory": project_inventory(inventory),
        "catalogue": project_catalogue(catalogue),
        "tool_results": project_tool_results(tool_results),
        "budgets": project_budgets(budgets),
        "output_schema": project_output_schema("ModelDraft"),
    }


def render_proposal_prompt(**kwargs: Any) -> RenderedPrompt:
    return render("propose", proposal_prompt_variables(**kwargs))


def repair_prompt_variables(
    *,
    validation_errors: str,
    previous_response: str,
    job_id: str,
    inventory: Any,
    catalogue: CatalogueView | None,
    tool_results: list[ToolResult],
    budgets: AgentBudgets,
) -> dict[str, str]:
    """The complete render map for `repair`.

    A repair is a *corrected proposal*, so it carries the same evidence the proposal
    call had. Sending the schema and the error alone would let a live model answer
    from nothing.
    """

    proposal = proposal_prompt_variables(
        job_id=job_id,
        inventory=inventory,
        catalogue=catalogue,
        tool_results=tool_results,
        budgets=budgets,
    )
    return {
        # The previous answer is model-authored, so it can contain
        # `</previous_response>` and close its own quote block. It is neutralised like
        # any other untrusted value; `validation_errors` comes from Pydantic and not
        # from the model, so it is not.
        "validation_errors": validation_errors,
        "previous_response": _bounded_text(str(projected(previous_response, "previous_response"))),
        "inventory": proposal["inventory"],
        "catalogue": proposal["catalogue"],
        "tool_results": proposal["tool_results"],
        "budgets": proposal["budgets"],
        "output_schema": proposal["output_schema"],
    }


def render_repair_prompt(*, validation_errors: str, previous_response: str, **proposal: Any) -> RenderedPrompt:
    return render(
        "repair",
        repair_prompt_variables(
            validation_errors=validation_errors,
            previous_response=previous_response,
            **proposal,
        ),
    )


__all__ = [
    "MAX_PROJECTED_FIELDS",
    "PROMPTS_DIR",
    "PromptError",
    "PromptSpec",
    "RenderedPrompt",
    "job_ref",
    "load_prompt",
    "manifest",
    "project_budgets",
    "project_catalogue",
    "project_inventory",
    "project_output_schema",
    "project_tool_results",
    "proposal_prompt_variables",
    "render",
    "render_proposal_prompt",
    "render_repair_prompt",
    "repair_prompt_variables",
]
