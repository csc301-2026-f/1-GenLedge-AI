"""Shared agent contracts and the US4 routing harness.

Public entrypoints for the US4 workstreams:

* `contracts` — the single typed contract surface, frozen at version 1.
* `graph` — `build_graph()` and `run_routing_job()`, the harness boundary.
* `state` — `RoutingJobState` and its reducers.
* `models` — `resolve_model_mode()` and the fake/live adapters.
* `tools` — the tool catalog and the dispatch contract.
* `prompts` — the projection allow-list and the versioned prompts.
* `repositories` — the repository protocol plus the in-memory doubles.

Import a submodule directly (`from app.agent.graph import run_routing_job`) rather
than relying on re-exports here: `init_agent` and `CONTRACT_VERSION` are the only
names this package promises.
"""

from .contracts import CONTRACT_VERSION

__all__ = ["CONTRACT_VERSION"]
