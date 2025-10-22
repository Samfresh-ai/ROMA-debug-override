from sentientresearchagent.hierarchical_agent_framework.node.task_node import TaskNode
from sentientresearchagent.hierarchical_agent_framework.context.agent_io_models import AgentTaskInput  # Correct import (resolves the error)
from sentientresearchagent.hierarchical_agent_framework.agents.adapters import ExecutorAdapter  # Base class for executors
from litellm import completion
import logging
import asyncio  # For potential async helpers

logger = logging.getLogger(__name__)

class DebuggerAgent(ExecutorAdapter):
    def __init__(self, model_id='openai/gpt-4o', system_prompt=None):
        # Factory injects AgnoAgent; pass None here for custom init
        super().__init__(agno_agent_instance=None, agent_name="DebuggerAgent")
        self.model_id = model_id
        self.system_prompt = system_prompt or "You are a log-based debugger for ROMA framework. Analyze for errors (e.g., imports, agent creation), suggest code fixes, and trace flows."  # <-- Full fallback prompt

    async def process(self, node: TaskNode, agent_task_input: AgentTaskInput, trace_manager: "TraceManager" = None) -> dict:
        """
        Analyzes log chunks for errors, suggests fixes, and traces issues.
        Integrates with ROMA's TraceManager for event logging.
        """
        logger.info(f"DebuggerAgent: Processing debug task for node {node.task_id}")

        # Optional: Leverage parent adapter logic (e.g., for base tracing/validation)
        # result = await super().process(node, agent_task_input, trace_manager)
        # if result: return result

        goal = agent_task_input.current_goal
        context = str(agent_task_input.context) if agent_task_input.context else ""  # Logs as string

        # Early exit for empty context
        if not context.strip():
            empty_result = {
                "query_used": goal,
                "output_text": "No log context provided—nothing to analyze.",
                "error_count": 0,
                "suggestions": []
            }
            if trace_manager:
                try:
                    trace_manager.add_trace(node.task_id, "debugger_analysis", {"summary": "Empty context", "full_output": ""})
                except Exception as trace_err:
                    logger.warning(f"Trace add failed (non-fatal): {trace_err}")
            return empty_result

        try:
            # Improved chunking with 20% overlap to avoid splitting mid-error
            chunk_size = 4000  # Conservative for tokens (~5000 chars)
            overlap = chunk_size // 5
            chunks = []
            for i in range(0, len(context), chunk_size - overlap):
                chunk = context[i:i + chunk_size]
                chunks.append(chunk)
            if not chunks:  # Fallback if context too short
                chunks = [context]

            results = []
            for i, chunk in enumerate(chunks):
                messages = [
                    {"role": "system", "content": self.system_prompt},  # <-- Uses stored prompt
                    {"role": "user", "content": f"Goal: {goal}\nLog Chunk {i+1}/{len(chunks)}: {chunk}"}
                ]
                try:
                    response = await completion(model=self.model_id, messages=messages, temperature=0.1)
                    if response and hasattr(response, 'choices') and response.choices:
                        content = response.choices[0].message.content
                        logger.debug(f"LLM response for chunk {i+1}: {content[:100]}...")  # Log snippet
                        results.append(content)
                    else:
                        logger.warning(f"No response from LLM for chunk {i+1}—check API keys/rates.")
                        results.append("LLM response failed—retry or check config.")
                except Exception as llm_err:
                    logger.error(f"LLM call failed for chunk {i+1}: {llm_err}")
                    results.append(f"LLM error: {str(llm_err)}")

            output = "\n--- Chunk Separator ---\n".join(results)

            # Integrate with ROMA tracing (safe: wrap in try-except)
            if trace_manager:
                try:
                    trace_data = {
                        "summary": output[:500] + "..." if len(output) > 500 else output,
                        "full_output": output
                    }
                    trace_manager.add_trace(node.task_id, "debugger_analysis", trace_data)
                    logger.debug(f"Trace added for node {node.task_id}")
                except Exception as trace_err:
                    logger.warning(f"Trace add failed (non-fatal): {trace_err}")

            # Structured output: Always return dict, count errors robustly
            error_keywords = ["error", "failed", "warning", "exception"]
            error_count = sum(context.lower().count(kw) for kw in error_keywords)

            # Extract suggestions with regex for reliability
            import re
            suggestions = re.findall(r'(?i)(?:fix|(?:suggest|recommend).*?:?\s*)(.+?)(?=\n|$)', output)

            return {
                "query_used": goal,
                "output_text": output,
                "error_count": error_count,
                "suggestions": [s.strip() for s in suggestions if s.strip()]
            }

        except Exception as e:
            logger.error(f"DebuggerAgent processing failed for node {node.task_id}: {e}", exc_info=True)
            safe_result = {
                "query_used": goal,
                "output_text": f"Debugger analysis failed: {str(e)}. Check server logs for details.",
                "error_count": 0,
                "suggestions": []
            }
            # Safe trace
            if trace_manager:
                try:
                    trace_manager.add_trace(node.task_id, "debugger_error", {"error": str(e)})
                except:
                    pass
            return safe_result

