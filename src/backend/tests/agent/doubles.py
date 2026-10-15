"""Shared test doubles for the US4 Person B suite.

`ScriptedModel` is the `ScriptedLlm` of `plans/LANGGRAPH_HARNESS_PLAN.md` §11.2: it
returns queued responses in order, so a node's repair, refusal, invalid-output and
tool-request paths can be driven without a provider. No test in this package
touches the network, an API key, or PostgreSQL.
"""

from __future__ import annotations

from typing import Iterable

from app.agent.contracts import InventoryView, ToolCallRequest
from app.agent.models import ModelRequest, ModelResponse
from app.agent.repositories import SNAPSHOT_ID, seeded_repository


def inventory() -> InventoryView:
    """The seeded fixture inventory, asserted non-optional for type checkers."""

    found = seeded_repository().get_inventory(SNAPSHOT_ID)
    assert found is not None
    return found


class ScriptedModel:
    """A `ModelClient` that answers from a queue and records every request."""

    name = "scripted"

    def __init__(self, responses: Iterable[ModelResponse | str | None]) -> None:
        self.queue: list[ModelResponse] = []
        for item in responses:
            if isinstance(item, ModelResponse):
                self.queue.append(item)
            elif item is None:
                self.queue.append(ModelResponse(text=""))
            else:
                self.queue.append(ModelResponse(text=item))
        self.requests: list[ModelRequest] = []

    def invoke(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self.queue:
            return ModelResponse(text="")
        return self.queue.pop(0)

    @property
    def calls(self) -> int:
        return len(self.requests)

    @property
    def repair_calls(self) -> int:
        return sum(1 for request in self.requests if request.repair)


class GreedyModel:
    """A model that never stops asking for tools.

    Used to drive the tool budget to its bound: a cooperating model would answer
    with a draft before the budget mattered, which is why the loop bound needs a
    deliberately non-cooperative double to be observable.
    """

    name = "greedy"

    def __init__(self, *, tool: str = "sample_rows", resource_id: str = "orders.lines[]") -> None:
        self.tool = tool
        self.resource_id = resource_id
        self.requests: list[ModelRequest] = []

    def invoke(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        index = len(self.requests)
        return ModelResponse(
            tool_calls=[
                ToolCallRequest(
                    id=f"greedy-call-{index}",
                    name=self.tool,
                    arguments={
                        "source_id": "source-orders-1",
                        "resource_id": self.resource_id,
                        "limit": 3,
                    },
                )
            ],
            input_tokens=10,
            output_tokens=5,
            stop_reason="tool_use",
        )

    @property
    def calls(self) -> int:
        return len(self.requests)
