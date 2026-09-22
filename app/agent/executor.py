"""Run validated, read-only tools with a small and explicit retry budget."""

import time

from app.agent.state import AgentState, Observation, TraceEvent
from app.schemas.plan import TaskStep
from app.schemas.tool import ToolError, ToolResult
from app.tools.registry import ToolRegistry


class Executor:
    def __init__(self, tools: ToolRegistry, max_retries: int = 1) -> None:
        if not 0 <= max_retries <= 2:
            raise ValueError("Tool retries must be between 0 and 2.")
        self.tools = tools
        self.max_retries = max_retries

    def execute(self, step: TaskStep, state: AgentState) -> Observation:
        arguments = step.arguments.model_dump()
        for retry_count in range(self.max_retries + 1):
            started = time.perf_counter()
            try:
                result = ToolResult.model_validate(self.tools.execute(step.tool, arguments))
                if result.tool != step.tool:
                    raise ValueError("Tool output belongs to a different tool.")
            except Exception:
                # Boundary for unexpected tool bugs; never expose raw exceptions.
                result = ToolResult(tool=step.tool, success=False, error=ToolError(
                    code="TOOL_INTERNAL_ERROR",
                    message="The tool failed unexpectedly; no retry was attempted.",
                    retryable=False,
                ))
            state.trace.append(TraceEvent(
                node="Executor",
                step_id=step.id,
                tool=step.tool,
                input_summary="Fields: " + ", ".join(sorted(arguments)),
                result_summary="Validated tool output." if result.success else "Tool failed.",
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                success=result.success,
                retry_count=retry_count,
                error_code=result.error.code if result.error else None,
            ))
            if result.success or not result.error or not result.error.retryable:
                break
            if retry_count < self.max_retries:
                time.sleep(0.1 * (retry_count + 1))
        return Observation(
            step_id=step.id,
            tool=step.tool,
            success=result.success,
            data=result.data,
            error=result.error,
            attempts=retry_count + 1,
        )
