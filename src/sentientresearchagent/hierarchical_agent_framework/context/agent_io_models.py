from pydantic import BaseModel, Field, field_validator, ConfigDict  # v2 full: no 'validator'
from typing import List, Any, Optional, Dict, Union
import warnings  # Suppress Pydantic warnings module-wide

# Suppress namespace warnings (catches model_ clashes during load)
warnings.filterwarnings("ignore", message=".*protected namespace.*", category=UserWarning, module="pydantic")

# Import reasoning types from agno for reasoning-enabled agents
try:
    from agno.reasoning.step import ReasoningStep
    REASONING_AVAILABLE = True
except ImportError:
    REASONING_AVAILABLE = False
    # Define minimal fallback types if agno is not available
    class ReasoningStep(BaseModel):
        title: Optional[str] = None
        action: Optional[str] = None
        result: Optional[str] = None
        reasoning: Optional[Union[str, Dict[str, Any]]] = None  # Allow both string and structured reasoning
        
        @field_validator('reasoning', mode='before')  # v2: field_validator + mode='before'
        @classmethod
        def process_reasoning(cls, v):
            """Convert structured reasoning to string if needed."""
            if isinstance(v, dict):
                # Convert structured reasoning to readable string
                parts = []
                if 'necessity' in v:
                    parts.append(f"Necessity: {v['necessity']}")
                if 'assumptions' in v and v['assumptions'] != 'N/A':
                    parts.append(f"Assumptions: {v['assumptions']}")
                if 'approach' in v:
                    parts.append(f"Approach: {v['approach']}")
                return " | ".join(parts) if parts else str(v)
            return v

        model_config = ConfigDict(protected_namespaces=())

# --- Plan Output Schemas (used by Planner Agents and NodeProcessor) ---
class SubTask(BaseModel):
    """Schema for a single sub-task planned by a Planner agent."""
    goal: str = Field(..., description="Precise description of the sub-task goal.")
    task_type: str = Field(..., description="Type of task (e.g., 'WRITE', 'THINK', 'SEARCH').")
    node_type: str = Field(default="PLAN", description="Node type ('EXECUTE' for atomic, 'PLAN' for complex). Defaults to 'PLAN' since atomizer will make final decision.")
    depends_on_indices: Optional[List[int]] = Field(default_factory=list, description="List of 0-based indices of other sub-tasks in *this current plan* that this sub-task depends on. If empty, it only depends on the parent plan completing.")

    model_config = ConfigDict(protected_namespaces=())

class PlanOutput(BaseModel):
    """Output schema for a Planner agent, detailing the sub-tasks."""
    sub_tasks: List[SubTask] = Field(..., description="List of planned sub-tasks.")
    reasoning_steps: Optional[List[ReasoningStep]] = Field(default=None, description="Reasoning steps if agent has reasoning enabled")

    model_config = ConfigDict(protected_namespaces=())

# --- Atomizer Output Schema ---
class AtomizerOutput(BaseModel):
    """Output schema for Atomizer agents."""
    is_atomic: bool = Field(..., description="True if the refined goal is atomic, False if complex and needs planning.")
    updated_goal: str = Field(..., description="The refined task goal after considering context.")
    reasoning_steps: Optional[List[ReasoningStep]] = Field(default=None, description="Reasoning steps if agent has reasoning enabled")

    model_config = ConfigDict(protected_namespaces=())

# --- Context Structure for Agents ---
class ContextItem(BaseModel):
    """A single piece of structured context provided to an agent."""
    source_task_id: str
    source_task_goal: str
    content: Any
    content_type_description: str

    model_config = ConfigDict(protected_namespaces=())

class ParentContextNode(BaseModel):
    """Represents context from a parent node in the hierarchy."""
    task_id: str
    goal: str
    layer: int
    task_type: str
    result_summary: Optional[str] = None
    key_insights: Optional[str] = None
    constraints_identified: Optional[str] = None
    requirements_specified: Optional[str] = None
    planning_reasoning: Optional[str] = None
    coordination_notes: Optional[str] = None
    timestamp_completed: Optional[str] = None

    model_config = ConfigDict(protected_namespaces=())

class ParentHierarchyContext(BaseModel):
    """Structured context from parent hierarchy, formatted for LLM consumption."""
    current_position: str = Field(..., description="Description of where this task sits in the hierarchy")
    parent_chain: List[ParentContextNode] = Field(default_factory=list, description="Ordered list from immediate parent to root")
    formatted_context: str = Field(..., description="LLM-friendly formatted text of the parent context")
    priority_level: str = Field(default="medium", description="Priority level: critical, high, medium, low")

    model_config = ConfigDict(protected_namespaces=())

# Enhanced AgentTaskInput
class AgentTaskInput(BaseModel):
    """Structured input provided to an agent for processing a task."""
    current_task_id: str
    current_goal: str
    current_task_type: str
    overall_project_goal: Optional[str] = None
    relevant_context_items: List[ContextItem] = Field(default_factory=list)
    parent_hierarchy_context: Optional[ParentHierarchyContext] = None
    formatted_full_context: Optional[str] = Field(None, description="Complete formatted context for LLM")

    model_config = ConfigDict(protected_namespaces=())

# --- Research Agent I/O Schemas ---
class WebSearchResultsOutput(BaseModel):
    """Output schema for a SearchExecutor agent, detailing the search results."""
    query_used: str = Field(..., description="The exact search query that was executed.")
    results: List[Dict[str, str]] = Field(..., description="A list of search results, each ideally with 'title', 'link', and 'snippet'.")
    reasoning_steps: Optional[List[ReasoningStep]] = Field(default=None, description="Reasoning steps if agent has reasoning enabled")

    model_config = ConfigDict(protected_namespaces=())

class AnnotationURLCitationModel(BaseModel):
    """Represents a URL citation annotation from the OpenAI web_search_preview tool."""
    title: Optional[str] = Field(None, description="The title of the cited page.")
    url: str = Field(..., description="The URL of the citation.")
    start_index: int = Field(..., description="The start index of the citation in the text.")
    end_index: int = Field(..., description="The end index of the citation in the text.")
    type: str = Field("url_citation", description="The type of annotation, typically 'url_citation'.")

    model_config = ConfigDict(protected_namespaces=())

class CustomSearcherOutput(BaseModel):
    """Structured output for the OpenAICustomSearchAdapter."""
    query_used: str = Field(..., description="The original query used for the search.")
    output_text_with_citations: str = Field(..., description="The main textual answer from the OpenAI model, including any inline citations.")
    text_content: Optional[str] = Field(None, description="The textual answer parsed from the nested structure (e.g., response.output[1].content[0].text), if available.")
    annotations: List[AnnotationURLCitationModel] = Field(default_factory=list, description="A list of URL annotations, if available from the nested structure.")
    reasoning_steps: Optional[List[ReasoningStep]] = Field(default=None, description="Reasoning steps if agent has reasoning enabled")

    model_config = ConfigDict(protected_namespaces=())

    def __str__(self) -> str:
        return self.output_text_with_citations

# Merged Generic ExecutorOutput (covers framework + your DebuggerAgent needs)
class ExecutorOutput(BaseModel):
    """Generic structured output for executor agents (e.g., text, search results, debug analysis)."""
    # Core generic fields (from original)
    result: Any = Field(..., description="Direct output (e.g., text, WebSearchResultsOutput, or dict).")
    replan_request: Optional['ReplanRequestDetails'] = Field(None, description="Replan details if needed.")
    reasoning_steps: Optional[List[ReasoningStep]] = Field(default=None, description="Reasoning steps if enabled.")
    
    # Specific extensions for structured cases like DebuggerAgent
    output_text: Optional[str] = Field(None, description="Main textual response.")
    suggestions: Optional[List[str]] = Field(default_factory=list, description="List of suggestions/fixes.")

    model_config = ConfigDict(protected_namespaces=())

# --- Execution History & Replanning ---
class ExecutionHistoryItem(BaseModel):
    """Represents a single item in the execution history (sibling or ancestor output)."""
    task_goal: str = Field(..., description="Goal of the historical task.")
    outcome_summary: str = Field(..., description="Brief summary of what the task achieved or produced.")
    full_output_reference_id: Optional[str] = Field(None, description="An ID to fetch the full output if needed.")
    executor_output: Optional[ExecutorOutput] = Field(None, description="Full ExecutorOutput if available.")  # Link to merged model

    model_config = ConfigDict(protected_namespaces=())

class ExecutionHistoryAndContext(BaseModel):
    """Structured execution history and context for the planner."""
    prior_sibling_task_outputs: List[ExecutionHistoryItem] = Field(default_factory=list)
    relevant_ancestor_outputs: List[ExecutionHistoryItem] = Field(default_factory=list)
    global_knowledge_base_summary: Optional[str] = Field(None)

    model_config = ConfigDict(protected_namespaces=())

class ReplanRequestDetails(BaseModel):
    """Structured feedback for a re-plan request."""
    failed_sub_goal: str = Field(..., description="The specific sub-goal that previously failed or requires re-planning.")
    reason_for_failure_or_replan: str = Field(..., description="Detailed explanation of why the previous attempt failed or why a re-plan is necessary.")
    previous_attempt_output_summary: Optional[str] = Field(None, description="Summary of what the failed attempt did produce, if anything.")
    specific_guidance_for_replan: Optional[str] = Field(None, description="Concrete suggestions on how to approach the re-plan differently.")

    model_config = ConfigDict(protected_namespaces=())

class PlannerInput(BaseModel):
    """Defines the structured input for the enhanced Planner Agent."""
    current_task_goal: str = Field(..., description="The specific goal for this planning instance.")
    overall_objective: str = Field(..., description="The ultimate high-level goal of the entire operation.")
    parent_task_goal: Optional[str] = Field(None, description="The goal of the immediate parent task. Null if root task.")
    planning_depth: Optional[int] = Field(0, description="Current recursion depth (e.g., 0 for initial, 1 for sub-tasks).")
    execution_history_and_context: ExecutionHistoryAndContext = Field(default_factory=ExecutionHistoryAndContext)
    replan_request_details: Optional[ReplanRequestDetails] = Field(None)
    global_constraints_or_preferences: Optional[List[str]] = Field(default_factory=list)

    model_config = ConfigDict(protected_namespaces=())

class PlanModifierInput(BaseModel):
    """Input model for an agent tasked with modifying an existing plan based on user feedback."""
    original_plan: PlanOutput = Field(description="The current plan (PlanOutput model) that needs modification.")
    user_modification_instructions: str = Field(description="Textual instructions from the user on how to modify the plan.")
    overall_objective: str = Field(description="The overarching goal that the original and revised plan must achieve.")
    parent_task_id: Optional[str] = Field(default=None, description="The ID of the parent task for which this plan is being modified.")
    planning_depth: Optional[int] = Field(default=None, description="The current planning depth/layer of the parent task.")

    model_config = ConfigDict(protected_namespaces=())

# --- Aggregator Output Schema ---
class AggregatorOutput(BaseModel):
    """Structured output for aggregator agents."""
    aggregated_content: str = Field(..., description="Combined/synthesized content from child tasks.")
    summary: Optional[str] = Field(default="", description="High-level summary of aggregation.")
    reasoning_steps: Optional[List[ReasoningStep]] = Field(default=None, description="Reasoning steps if enabled.")

    model_config = ConfigDict(protected_namespaces=())