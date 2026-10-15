"""Node-level execution deadlines for the two slow seams.

`AgentBudgets.model_node_timeout_seconds` and `AgentBudgets.tool_node_timeout_seconds`
are part of the frozen budget surface and were read nowhere: a hung connector blocked
the worker indefinitely, and a model call that overran its node budget was billed,
reported and used as if it had been on time. This module is the one place that turns
those two declarations into behaviour, and it is explicit about the different strength
of the guarantee each one can actually carry.

`plans/LANGGRAPH_HARNESS_PLAN.md` §6.5 puts both in the **client-side** layer — "per
tool call: `AgentBudgets.tool_node_timeout_seconds`; a hung connector fails its call,
not the node" — with framework-level node timeouts deferred to experiment E-3. The
graph runs its nodes synchronously, so the seam that calls the connector or the
provider is the boundary that owns the deadline, and that is where this module is
used.

Two mechanisms, deliberately different:

* **`run_with_deadline` — a real bound, for the tool call.** The connector is called
  on a daemon worker thread and the batch node waits at most the budget. A connector
  that never returns therefore fails *its call* with a typed `connector_timeout`
  result, which is exactly the plan's requirement; the run continues to `propose`
  with the timeout as data, and the tool budget bounds how often that can happen.
  One honest caveat: Python cannot preempt a thread, so a truly stuck connector leaves
  its daemon worker behind. The worker holds nothing the run needs, and the *caller*
  is bounded — which is the guarantee, and the reason the worker is a daemon rather
  than a pool thread that would block interpreter shutdown.

* **`exceeded` — an elapsed-time check, for the model call.** A synchronous provider
  SDK call cannot be preempted in-process either, so no in-node mechanism can enforce
  a hard deadline on it; claiming otherwise would be the "synchronous blocking call
  described as safely time-limited" this area was reviewed for. What the node *can*
  guarantee is narrower, and is exactly this: an answer that overran the budget is
  **recorded durably, refused, and never becomes the run's draft**. The run ends as a
  typed, retryable `model_unavailable` failure instead of continuing on work that spent
  the budget. This is a post-call check, not a pre-call one — there is no cumulative
  "the node has already spent its budget, so make no call" gate, because the elapsed
  time of a *single* invocation is what this budget names; the job-wide pre-call gate is
  `AgentBudgets.max_wall_clock_seconds`, checked in `nodes._budget_stop` before any
  call. The hard per-attempt bound is the provider client's own request timeout
  (`GENLEDGE_LLM_TIMEOUT_SECONDS`, derived in `models.derived_model_timeout_seconds`),
  which is the plan's `llm.py` transport level.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable

from app.agent.contracts import AgentBudgets

#: How long a batch node waits for one connector call when the budget does not say.
#: Kept as a module constant so the derivation is stated once; `AgentBudgets` is the
#: authority and this is only the fallback for a hand-built object.
DEFAULT_TOOL_CALL_TIMEOUT_SECONDS = 120

#: The margin `plans/LANGGRAPH_HARNESS_PLAN.md` §6.5 adds to a model-call attempt on
#: top of `request_timeout × (1 + retries)`.
MODEL_CALL_MARGIN_SECONDS = 60


class DeadlineExceeded(TimeoutError):
    """One tool call did not answer inside `tool_node_timeout_seconds`."""

    def __init__(self, name: str, timeout_seconds: float) -> None:
        super().__init__(
            f"{name} did not answer within tool_node_timeout_seconds ({timeout_seconds:g}s)"
        )
        self.tool_name = name
        self.timeout_seconds = timeout_seconds


def tool_call_timeout_seconds(budgets: AgentBudgets) -> float:
    """The per-tool-call deadline, or `0` when the budget disables it.

    `ge=0` on the contract means `0` is a legal value, and it is read as "do not bound
    this" rather than "fail immediately": a zero-second deadline would refuse every
    call, which is not a configuration anyone means. It is also what keeps the check a
    pure addition — with the budget at `0` the call runs exactly as it did before this
    module existed.
    """

    return float(getattr(budgets, "tool_node_timeout_seconds", DEFAULT_TOOL_CALL_TIMEOUT_SECONDS) or 0)


def model_node_timeout_seconds(budgets: AgentBudgets) -> float:
    """The model **node** deadline, or `0` when the budget disables it."""

    return float(getattr(budgets, "model_node_timeout_seconds", 0) or 0)


def run_with_deadline(
    action: Callable[[], Any],
    *,
    timeout_seconds: float,
    label: str,
) -> Any:
    """Run `action` and wait at most `timeout_seconds` for it.

    Raises `DeadlineExceeded` when the deadline passes, otherwise returns the action's
    result — or **re-raises its exception**, so the caller's existing error handling
    sees exactly what a direct call would have produced. `timeout_seconds <= 0` runs
    the action on the calling thread: no thread is created for a disabled deadline,
    and the call is byte-for-byte the pre-existing behaviour.

    The worker is a daemon thread on purpose. Returning early while the worker is still
    running is the whole point of `wait_for`, and a non-daemon worker would keep the
    interpreter alive at shutdown for a connector that may never return.
    """

    if timeout_seconds <= 0:
        return action()

    outcome: "queue.Queue[tuple[bool, Any]]" = queue.Queue(maxsize=1)

    def target() -> None:
        try:
            outcome.put((True, action()))
        except BaseException as error:  # noqa: BLE001 - relayed to the caller verbatim
            outcome.put((False, error))

    worker = threading.Thread(target=target, name=f"agent-deadline:{label}", daemon=True)
    worker.start()
    try:
        ok, value = outcome.get(timeout=timeout_seconds)
    except queue.Empty:
        raise DeadlineExceeded(label, timeout_seconds) from None
    if ok:
        return value
    raise value


def exceeded(started: float, timeout_seconds: float, *, now: float) -> bool:
    """True when `timeout_seconds` has passed since `started`.

    `timeout_seconds <= 0` means the budget does not bound this node. `now` is passed
    in rather than read here so a caller's two checks share one clock reading.
    """

    if timeout_seconds <= 0:
        return False
    return (now - started) >= timeout_seconds


__all__ = [
    "DEFAULT_TOOL_CALL_TIMEOUT_SECONDS",
    "MODEL_CALL_MARGIN_SECONDS",
    "DeadlineExceeded",
    "exceeded",
    "model_node_timeout_seconds",
    "run_with_deadline",
    "tool_call_timeout_seconds",
]
