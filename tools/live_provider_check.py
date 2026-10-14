"""One live model call — the only check a stub cannot make.

Everything else in this slice is verified against fakes: the connector, the model,
the repository. That leaves exactly one unvalidated assumption — that the *wire
format* `LiveModel` builds is one a real provider accepts (native structured output,
bound tools with `tool_choice: auto`). This script closes it with a single job.

**Opt-in and never in the test suite.** It needs a key and the network, which
`plans/LANGGRAPH_HARNESS_PLAN.md` §11.5 forbids for tests.

    pip install anthropic
    $env:ANTHROPIC_API_KEY = "sk-ant-..."          # or GENLEDGE_LLM_API_KEY
    python tools/live_provider_check.py

Anthropic-compatible endpoints work too, which is how you can point this at a
gateway fronting another model:

    $env:GENLEDGE_LLM_BASE_URL = "https://your-gateway.example/v1"
    $env:GENLEDGE_LLM_MODEL    = "glm-5.3"
    python tools/live_provider_check.py

Exit code 0 means the provider answered, the answer validated against `ModelDraft`,
and the loop completed. Any failure prints the provider's own error.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src" / "backend"))

from app.agent.contracts import AgentBudgets, ModelDraft  # noqa: E402
from app.agent.graph import run_routing_job  # noqa: E402
from app.agent.models import LiveModel, provider_configured, resolve_model_mode  # noqa: E402
from app.agent.repositories import SNAPSHOT_ID, seeded_repository  # noqa: E402

KEY_VARS = ("GENLEDGE_LLM_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")


def main() -> int:
    if not provider_configured():
        print("No provider configuration found.")
        print(f"Set one of: {', '.join(KEY_VARS)}")
        print("Optionally set GENLEDGE_LLM_BASE_URL / GENLEDGE_LLM_MODEL to use a gateway.")
        return 2

    resolved = resolve_model_mode("live")
    print(f"resolved   : {resolved.banner}")
    print(f"base_url   : {'set' if os.environ.get('GENLEDGE_LLM_BASE_URL') or os.environ.get('ANTHROPIC_BASE_URL') else 'default'}")

    try:
        import anthropic  # noqa: F401,PLC0415
    except ImportError:
        print("The anthropic SDK is not installed: python -m pip install anthropic")
        return 2

    repository = seeded_repository()
    model = LiveModel(
        provider=resolved.provider,
        model=resolved.model,
        effort=os.environ.get("GENLEDGE_LLM_EFFORT", "medium"),
        max_output_tokens=int(os.environ.get("GENLEDGE_LLM_MAX_OUTPUT_TOKENS", "4096")),
        timeout_seconds=float(os.environ.get("GENLEDGE_LLM_TIMEOUT_SECONDS", "300")),
        max_retries=int(os.environ.get("GENLEDGE_LLM_MAX_RETRIES", "2")),
        api_key=os.environ.get("GENLEDGE_LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"),
        base_url=os.environ.get("GENLEDGE_LLM_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL"),
    )

    started = time.monotonic()
    run = run_routing_job(
        job_id="live-provider-check",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        model=model,
        budgets=AgentBudgets(max_tool_calls=4, max_model_calls=4),
    )
    elapsed = time.monotonic() - started

    print(f"status     : {run.status}")
    print(f"model calls: {run.final_state['model_calls_used']}")
    print(f"tool calls : {run.final_state['tool_calls_used']}")
    print(f"tokens     : {run.final_state['tokens_used']}")
    print(f"latency    : {elapsed:.1f}s")
    for response in run.model_responses:
        if response.error_code:
            print(f"provider   : {response.error_code} — {response.error_message}")

    if run.failure is not None:
        print(f"FAILURE    : {run.failure.code} — {run.failure.message}")
        return 1
    if not isinstance(run.model_draft, ModelDraft):
        print("FAILURE    : the provider did not return a valid ModelDraft")
        return 1

    print(f"tables     : {sorted(table.id for table in run.model_draft.tables)}")
    print(f"unresolved : {len(run.model_draft.unresolved)} item(s)")
    print()
    print("OK: the live wire format works — structured output validated and the loop completed.")
    if run.final_state["tool_calls_used"] == 0:
        print("NOTE: the provider answered without requesting a tool. The tool path is")
        print("      therefore unverified by this run; the API accepted the bound tools.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
