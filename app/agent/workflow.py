"""Small bounded loop: Plan -> Act -> Observe -> collect Phase 1 results."""

import time

from pydantic import ValidationError

from app.agent.executor import Executor
from app.agent.planner import Planner
from app.agent.state import AgentState, TraceEvent
from app.schemas.profile import ProfileData
from app.schemas.report import Phase1Report
from app.schemas.tool import SearchJobsData, ToolError
from app.services.llm import LLMError, LLMService
from app.tools.registry import ToolRegistry


class CareerAgent:
    def __init__(self, llm: LLMService, tools: ToolRegistry, max_tool_retries: int = 1) -> None:
        self.llm = llm
        self.planner = Planner(llm, tools)
        self.executor = Executor(tools, max_tool_retries)

    def run(self, goal: str) -> AgentState:
        state = AgentState(goal=goal)
        started = time.perf_counter()
        event_start = len(self.llm.events)
        try:
            state.plan = self.planner.create_plan(state.goal).steps
        except LLMError as error:
            state.errors.append(ToolError(
                code=error.code, message=error.message, retryable=False,
            ))
        finally:
            self._copy_llm_trace(state, event_start)
        state.trace.append(TraceEvent(
            node="Planner",
            input_summary="Goal and allowed tool schemas.",
            result_summary=f"{len(state.plan)} validated steps.",
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            success=bool(state.plan),
            error_code=state.errors[-1].code if state.errors else None,
        ))
        if state.errors:
            state.status = "failed"
            return state

        state.status = "executing"
        for index, step in enumerate(state.plan):
            state.current_step = index
            step.status = "running"
            observation = self.executor.execute(step, state)
            state.observations.append(observation)
            step.status = "completed" if observation.success else "failed"
            if not observation.success:
                state.errors.append(observation.error or ToolError(
                    code="TOOL_FAILED", message="Tool returned no usable result.", retryable=False,
                ))
                state.status = "failed"
                return state

        state.current_step = len(state.plan)
        self._collect_report(state)
        return state

    def _copy_llm_trace(self, state: AgentState, start: int) -> None:
        for event in self.llm.events[start:]:
            state.trace.append(TraceEvent(
                node="LLM",
                input_summary=str(event.get("operation", "structured_output")),
                result_summary="Provider/validation attempt; content omitted.",
                duration_ms=event.get("duration_ms", 0),
                success=event.get("success", False),
                retry_count=max(0, event.get("attempt", 1) - 1),
                error_code=event.get("error_code"),
            ))

    def _collect_report(self, state: AgentState) -> None:
        """Check output shape/completeness; independent semantic Verifier is Phase 3."""
        started = time.perf_counter()
        try:
            profile = ProfileData.model_validate(state.observations[0].data)
            searches = [SearchJobsData.model_validate(item.data)
                        for item in state.observations[1:]]
            if not any(search.items for search in searches):
                state.errors.append(ToolError(
                    code="NO_SEARCH_RESULTS",
                    message="No sources were found. Refine the query or change the search mode.",
                    retryable=False,
                ))
            else:
                limitations = [
                    "Phase 1 collects a profile and search sources only.",
                    "No job extraction, skill ranking, gap analysis or seven-day plan yet.",
                    "Keyword matching does not verify full relevance, eligibility or vacancy availability.",
                ]
                for search in searches:
                    limitations.extend(search.warnings)
                if any(search.source_mode == "sample" for search in searches):
                    limitations.append("Synthetic job samples are demo data, not current market evidence.")
                state.final_report = Phase1Report(
                    goal=state.goal,
                    summary="Collected the skill profile and search sources; further analysis is pending.",
                    profile=profile,
                    searches=searches,
                    limitations=list(dict.fromkeys(limitations)),
                )
        except ValidationError:
            state.errors.append(ToolError(
                code="REPORT_VALIDATION_FAILED",
                message="Collected tool data does not match the report schema.",
                retryable=False,
            ))
        state.status = "failed" if state.errors else "completed"
        state.trace.append(TraceEvent(
            node="Report",
            input_summary=f"{len(state.observations)} observations.",
            result_summary="Phase 1 collection complete." if state.final_report else "Incomplete evidence.",
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            success=state.final_report is not None,
            error_code=state.errors[-1].code if state.errors else None,
        ))
