"""Integration contracts for the bounded Phase 1 workflow and CLI."""

import ast
import io
import json
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app import cli
from app.agent.planner import demo_plan_json
from app.agent.workflow import CareerAgent
from app.schemas.plan import Plan
from app.schemas.tool import ToolError, ToolResult
from app.services import FakeProvider, LLMService, LLMSettings
from app.tools.registry import ToolRegistry

REPO_DIR = Path(__file__).resolve().parents[1]
GOAL = "Junior AI Agent Engineer Python"


def plan_dict():
    return json.loads(demo_plan_json(GOAL))


def temporary_failure():
    return ToolResult(tool="search_jobs", success=False, error=ToolError(
        code="TEST_TIMEOUT", message="Test transport timeout.", retryable=True,
    ))


class ScriptedRegistry(ToolRegistry):
    """Override one tool boundary while preserving the real remaining tools."""

    def __init__(self, scripted=None, scripted_tool="search_jobs"):
        super().__init__(REPO_DIR / "data", search_mode="sample")
        self.scripted = list(scripted or [])
        self.scripted_tool = scripted_tool
        self.calls = []

    def execute(self, name, arguments):
        self.calls.append((name, deepcopy(arguments)))
        if name == self.scripted_tool and self.scripted:
            result = self.scripted.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return super().execute(name, arguments)


class PlanContractTests(unittest.TestCase):
    def test_rejects_unexecutable_plans_before_any_tool_dispatch(self):
        variants = []
        bad_args = plan_dict()
        bad_args["steps"][1]["arguments"]["query"] = 42
        variants.append(("wrong argument type", bad_args))
        unknown = plan_dict()
        unknown["steps"][1]["tool"] = "shell"
        variants.append(("unknown tool", unknown))
        wrong_order = plan_dict()
        wrong_order["steps"].reverse()
        for index, step in enumerate(wrong_order["steps"], 1):
            step["id"] = index
        variants.append(("wrong tool order", wrong_order))
        wrong_id = plan_dict()
        wrong_id["steps"][1]["id"] = 4
        variants.append(("nonconsecutive ids", wrong_id))
        missing_search = plan_dict()
        missing_search["steps"] = missing_search["steps"][:1]
        variants.append(("too few steps", missing_search))
        too_many = plan_dict()
        too_many["steps"] += [deepcopy(too_many["steps"][1]) for _ in range(3)]
        for index, step in enumerate(too_many["steps"], 1):
            step["id"] = index
        variants.append(("too many steps", too_many))
        already_run = plan_dict()
        already_run["steps"][0]["status"] = "completed"
        variants.append(("initial status not pending", already_run))
        unsafe_file = plan_dict()
        unsafe_file["steps"][0]["arguments"]["profile_name"] = "../.env"
        variants.append(("profile allowlist", unsafe_file))
        for label, invalid in variants:
            with self.subTest(label=label):
                with self.assertRaises(ValidationError):
                    Plan.model_validate(invalid)
                registry = ScriptedRegistry()
                llm = LLMService(FakeProvider([json.dumps(invalid)]), max_repair_attempts=0)
                state = CareerAgent(llm, registry).run(GOAL)
                self.assertEqual(state.status, "failed")
                self.assertEqual(registry.calls, [])
                self.assertEqual(state.errors[0].code, "structured_output_invalid")


class WorkflowTests(unittest.TestCase):
    def agent(self, responses=None, registry=None, max_tool_retries=1):
        provider = FakeProvider(responses if responses is not None else [demo_plan_json(GOAL)])
        return CareerAgent(LLMService(provider), registry or ScriptedRegistry(), max_tool_retries)

    def test_full_run_records_plan_observations_report_and_provenance(self):
        state = self.agent().run(GOAL)
        self.assertEqual(state.status, "completed")
        self.assertEqual(state.current_step, len(state.plan))
        self.assertEqual([step.status for step in state.plan], ["completed", "completed"])
        self.assertEqual([item.tool for item in state.observations], ["read_profile", "search_jobs"])
        self.assertTrue(all(item.success and item.attempts == 1 for item in state.observations))
        self.assertTrue(state.final_report.profile.sample)
        self.assertGreater(state.final_report.source_count, 0)
        self.assertTrue(all(search.source_mode == "sample" for search in state.final_report.searches))
        self.assertEqual([item.node for item in state.trace],
                         ["LLM", "Planner", "Executor", "Executor", "Report"])
        self.assertFalse(state.errors)

    def test_invalid_json_or_plan_schema_is_repaired_before_execution(self):
        invalid_plan = plan_dict()
        invalid_plan["steps"][1]["tool"] = "UNKNOWN_TEST_TOOL"
        for invalid, code in (("invalid json", "invalid_json"),
                              (json.dumps(invalid_plan), "schema_validation_failed")):
            with self.subTest(code=code):
                registry = ScriptedRegistry()
                state = self.agent([invalid, demo_plan_json(GOAL)], registry).run(GOAL)
                self.assertEqual(state.status, "completed")
                attempts = [item for item in state.trace if item.node == "LLM"]
                self.assertEqual([item.success for item in attempts], [False, True])
                self.assertEqual(attempts[0].error_code, code)
                self.assertEqual(attempts[1].retry_count, 1)
                self.assertEqual(len(registry.calls), 2)

    def test_exhausted_repair_never_runs_tools_or_logs_untrusted_content(self):
        registry = ScriptedRegistry()
        sentinel = "PRIVATE_TEST_SENTINEL"
        state = self.agent([sentinel, sentinel], registry).run(GOAL)
        self.assertEqual(state.status, "failed")
        self.assertEqual(registry.calls, [])
        self.assertFalse(state.observations)
        self.assertIsNone(state.final_report)
        self.assertEqual(state.errors[0].code, "structured_output_invalid")
        safe_metadata = [item.model_dump() for item in [*state.errors, *state.trace]]
        self.assertNotIn(sentinel, json.dumps(safe_metadata))

    def test_temporary_tool_failure_recovers_and_keeps_attempt_history(self):
        registry = ScriptedRegistry([temporary_failure()])
        with patch("app.agent.executor.time.sleep") as sleep:
            state = self.agent(registry=registry).run(GOAL)
        self.assertEqual(state.status, "completed")
        search_events = [item for item in state.trace if item.tool == "search_jobs"]
        self.assertEqual([item.success for item in search_events], [False, True])
        self.assertEqual([item.retry_count for item in search_events], [0, 1])
        self.assertEqual(state.observations[-1].attempts, 2)
        sleep.assert_called_once()

    def test_permanent_failure_stops_without_retry_or_later_steps(self):
        failure = ToolResult(tool="read_profile", success=False, error=ToolError(
            code="PROFILE_DENIED", message="Profile unavailable.", retryable=False,
        ))
        registry = ScriptedRegistry([failure], scripted_tool="read_profile")
        state = self.agent(registry=registry, max_tool_retries=2).run(GOAL)
        self.assertEqual(state.status, "failed")
        self.assertEqual([step.status for step in state.plan], ["failed", "pending"])
        self.assertEqual([name for name, _ in registry.calls], ["read_profile"])
        self.assertEqual(state.observations[0].attempts, 1)

    def test_retry_budget_stops_repeated_temporary_failure(self):
        registry = ScriptedRegistry([temporary_failure() for _ in range(4)])
        with patch("app.agent.executor.time.sleep"):
            state = self.agent(registry=registry, max_tool_retries=2).run(GOAL)
        self.assertEqual(state.status, "failed")
        self.assertEqual(state.observations[-1].attempts, 3)
        self.assertEqual(len([name for name, _ in registry.calls if name == "search_jobs"]), 3)
        self.assertEqual(len(registry.scripted), 1)

    def test_malformed_return_wrong_tool_and_exception_are_contained(self):
        bad_returns = [None, {"success": True}, RuntimeError("PRIVATE_TEST_SENTINEL"),
                       ToolResult(tool="other_tool", success=True, data={})]
        for bad in bad_returns:
            with self.subTest(kind=type(bad).__name__):
                registry = ScriptedRegistry([bad])
                state = self.agent(registry=registry).run(GOAL)
                self.assertEqual(state.status, "failed")
                self.assertEqual(state.errors[0].code, "TOOL_INTERNAL_ERROR")
                self.assertEqual(state.observations[-1].attempts, 1)
                self.assertNotIn("PRIVATE_TEST_SENTINEL", state.model_dump_json())

    def test_semantically_wrong_tool_data_fails_report_validation(self):
        bad_profile = ToolResult(tool="read_profile", success=True, data={"unexpected": True})
        registry = ScriptedRegistry([bad_profile], scripted_tool="read_profile")
        state = self.agent(registry=registry).run(GOAL)
        self.assertEqual(state.status, "failed")
        self.assertIsNone(state.final_report)
        self.assertEqual(state.errors[0].code, "REPORT_VALIDATION_FAILED")

    def test_empty_search_cannot_be_reported_as_success(self):
        registry = ToolRegistry(REPO_DIR / "data", search_mode="web", search_backend=lambda *_: [])
        state = self.agent(registry=registry).run(GOAL)
        self.assertEqual(state.status, "failed")
        self.assertEqual(state.errors[0].code, "NO_SEARCH_RESULTS")
        self.assertIsNone(state.final_report)
        self.assertFalse(state.trace[-1].success)

    def test_reusing_agent_does_not_copy_previous_run_trace(self):
        agent = self.agent(["bad json", demo_plan_json(GOAL), demo_plan_json(GOAL)])
        first = agent.run(GOAL)
        second = agent.run(GOAL)
        self.assertEqual(first.status, "completed")
        self.assertEqual(second.status, "completed")
        self.assertEqual(len([item for item in first.trace if item.node == "LLM"]), 2)
        self.assertEqual(len([item for item in second.trace if item.node == "LLM"]), 1)
        self.assertTrue(all(item.success for item in second.trace))
        self.assertIsNot(first.observations, second.observations)


class CLIContractTests(unittest.TestCase):
    def invoke(self, arguments):
        output = io.StringIO()
        with patch("app.cli.LLMSettings.from_env", return_value=LLMSettings()), redirect_stdout(output):
            code = cli.main(arguments)
        return code, json.loads(output.getvalue())

    def test_invalid_goal_rejected_before_provider_construction_without_echo(self):
        for goal in ("   ", "PRIVATE_TEST_SENTINEL" * 101):
            with self.subTest(length=len(goal)):
                output = io.StringIO()
                with patch("app.cli.build_llm") as builder, redirect_stdout(output):
                    code = cli.main(["--goal", goal, "--json"])
                self.assertEqual(code, 1)
                builder.assert_not_called()
                self.assertEqual(json.loads(output.getvalue())["errors"][0]["code"], "invalid_input")
                self.assertNotIn("PRIVATE_TEST_SENTINEL", output.getvalue())

    def test_json_output_identifies_fake_model_and_synthetic_search(self):
        code, output = self.invoke(["--goal", GOAL, "--provider", "fake", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(output["run_mode"], {"provider": "fake", "search": "sample",
                                              "simulated_failures": False})
        self.assertEqual(output["status"], "completed")

    def test_recovery_demo_rejects_live_model_or_web_before_model_creation(self):
        for mode in (["--provider", "deepseek"], ["--provider", "fake", "--search-mode", "web"]):
            with self.subTest(mode=mode):
                with patch("app.cli.build_llm") as builder:
                    code, output = self.invoke([*mode, "--demo-recovery", "--json"])
                self.assertEqual(code, 1)
                self.assertEqual(output["errors"][0]["code"], "invalid_demo_mode")
                builder.assert_not_called()

    def test_recovery_demo_is_explicit_and_finishes_after_two_faults(self):
        with patch("app.agent.executor.time.sleep"):
            code, output = self.invoke(["--goal", GOAL, "--demo-recovery", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(output["run_mode"]["simulated_failures"])
        failure_codes = [item["error_code"] for item in output["trace"] if not item["success"]]
        self.assertEqual(failure_codes, ["invalid_json", "SIMULATED_TIMEOUT"])

    def test_business_modules_do_not_import_vendor_sdk(self):
        violations = []
        for directory in ("agent", "tools", "schemas"):
            for source in (REPO_DIR / "app" / directory).rglob("*.py"):
                tree = ast.parse(source.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    names = ([item.name for item in node.names] if isinstance(node, ast.Import)
                             else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                    if any(name.split(".")[0] in {"openai", "deepseek"} for name in names):
                        violations.append(str(source.relative_to(REPO_DIR)))
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
