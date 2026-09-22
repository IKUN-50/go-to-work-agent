"""Read-only CLI entry point. No model calls happen when this module is imported."""

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from pydantic import ValidationError

from app.agent.planner import demo_plan_json
from app.agent.state import AgentState
from app.agent.workflow import CareerAgent
from app.schemas.tool import ToolError, ToolResult
from app.services import LLMError, LLMSettings, build_llm
from app.tools.registry import ToolRegistry

REPO_DIR = Path(__file__).resolve().parents[1]
DEFAULT_GOAL = "研究 Junior AI Agent Engineer 岗位并读取我的技能档案"


class RecoveryDemoTools(ToolRegistry):
    """Deliberate fixture fault, enabled only by the explicit offline demo flag."""

    def __init__(self, data_dir: Path | None = None) -> None:
        super().__init__(data_dir, search_mode="sample")
        self.failed_once = False

    def execute(self, name: str, arguments: dict) -> ToolResult:
        if name == "search_jobs" and not self.failed_once:
            self.failed_once = True
            return ToolResult(tool=name, success=False, error=ToolError(
                code="SIMULATED_TIMEOUT", message="Deliberately simulated demo timeout.",
                retryable=True,
            ))
        return super().execute(name, arguments)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Phase 1 career research collector")
    result.add_argument("--goal", default=DEFAULT_GOAL)
    result.add_argument("--provider", choices=["fake", "deepseek"], default=None)
    result.add_argument("--search-mode", choices=["sample", "web"], default="sample")
    result.add_argument("--data-dir", type=Path, default=REPO_DIR / "data")
    result.add_argument("--max-tool-retries", type=int, choices=[0, 1, 2], default=1)
    result.add_argument("--demo-recovery", action="store_true",
                        help="Simulate malformed model output and one search timeout; offline only.")
    result.add_argument("--json", action="store_true", help="Print the complete state as JSON.")
    return result


def print_result(state: AgentState, provider: str, search_mode: str, recovery: bool) -> None:
    print(f"Provider: {provider} | Search: {search_mode} | Status: {state.status}")
    if provider == "fake":
        print("OFFLINE MODEL: the plan is scripted, not a live model response.")
    if search_mode == "sample":
        print("SYNTHETIC SOURCES: demo job samples, not current job-market evidence.")
    if recovery:
        print("DEMO FAULTS: one invalid model output and one tool timeout were deliberately injected.")
    print("\nExecution trace:")
    for item in state.trace:
        name = item.tool or item.node
        if item.node == "LLM":
            name = item.input_summary
        outcome = "success" if item.success else "failed"
        error = f" ({item.error_code})" if item.error_code else ""
        print(f"  {name:20} {outcome:7} retry={item.retry_count} {item.duration_ms:.1f}ms{error}")
    for error in state.errors:
        print(f"Error [{error.code}]: {error.message}")
    if state.final_report:
        report = state.final_report
        print(f"\nPhase 1 report: {report.source_count} unique sources collected.")
        print("Profile: " + ("sample" if report.profile.sample else "user-provided"))
        print("Skills: " + ", ".join(f"{name}={level}" for name, level in report.profile.skills.items()))
        shown_urls: set[str] = set()
        for search in report.searches:
            for item in search.items:
                if item.url in shown_urls:
                    continue
                shown_urls.add(item.url)
                print(f"  [{item.source_kind}] {item.title}\n    {item.url}")
        print("\nLimitations:")
        for limitation in report.limitations:
            print("  - " + limitation)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        # Validate before contacting any paid or network provider.
        goal = AgentState(goal=args.goal).goal
        settings = LLMSettings.from_env(REPO_DIR / ".env")
        if args.provider:
            settings = replace(settings, provider=args.provider)
        if args.demo_recovery and (settings.provider != "fake" or args.search_mode != "sample"):
            raise LLMError("invalid_demo_mode", "Recovery demo requires fake provider and sample sources.")
        responses = [demo_plan_json(goal)]
        if args.demo_recovery:
            responses.insert(0, "deliberately invalid json")
            settings = replace(settings, max_repair_attempts=1)
        llm = build_llm(settings, fake_responses=responses)
        tools = (RecoveryDemoTools(args.data_dir) if args.demo_recovery
                 else ToolRegistry(args.data_dir, search_mode=args.search_mode))
        state = CareerAgent(llm, tools, args.max_tool_retries).run(goal)
    except (LLMError, ValidationError, OSError) as error:
        code = error.code if isinstance(error, LLMError) else "invalid_input"
        message = error.message if isinstance(error, LLMError) else "Goal or local configuration is invalid."
        if args.json:
            print(json.dumps({"status": "failed", "errors": [{"code": code, "message": message}]}, ensure_ascii=False))
        else:
            print(f"Error [{code}]: {message}")
        return 1
    if args.json:
        output = state.model_dump(mode="json")
        output["run_mode"] = {"provider": settings.provider, "search": args.search_mode,
                              "simulated_failures": args.demo_recovery}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_result(state, settings.provider, args.search_mode, args.demo_recovery)
    return 0 if state.status == "completed" else 1
