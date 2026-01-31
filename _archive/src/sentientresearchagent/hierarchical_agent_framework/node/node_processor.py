from typing import List, Optional, Any, Dict, TYPE_CHECKING
from pydantic import BaseModel, ConfigDict
from loguru import logger

from sentientresearchagent.hierarchical_agent_framework.node.hitl_coordinator import HITLCoordinator
from sentientresearchagent.hierarchical_agent_framework.node.inode_handler import INodeHandler
from sentientresearchagent.hierarchical_agent_framework.node_handlers import AggregateHandler as AggregatingNodeHandler, ReplanHandler as NeedsReplanNodeHandler, ReadyNodeHandler, HandlerContext
from sentientresearchagent.hierarchical_agent_framework.node.task_node import TaskNode, TaskStatus, NodeType, TaskType
from sentientresearchagent.hierarchical_agent_framework.context.knowledge_store import KnowledgeStore
from sentientresearchagent.hierarchical_agent_framework.context.agent_io_models import (
    AgentTaskInput, PlanOutput, AtomizerOutput, ContextItem,
    PlannerInput, ReplanRequestDetails,
    CustomSearcherOutput, PlanModifierInput
)
from sentientresearchagent.hierarchical_agent_framework.agents.registry import AgentRegistry
from sentientresearchagent.hierarchical_agent_framework.agents.base_adapter import BaseAdapter
from sentientresearchagent.hierarchical_agent_framework.context.context_builder import (
    resolve_context_for_agent
)
from sentientresearchagent.hierarchical_agent_framework.context.planner_context_builder import resolve_input_for_planner_agent
from sentientresearchagent.hierarchical_agent_framework.agents.utils import get_context_summary, TARGET_WORD_COUNT_FOR_CTX_SUMMARIES
from sentientresearchagent.hierarchical_agent_framework.agent_blueprints import AgentBlueprint, get_blueprint_by_name
from .node_creation_utils import SubNodeCreator
from .node_atomizer_utils import NodeAtomizer
from .node_configs import NodeProcessorConfig
from sentientresearchagent.config import SentientConfig
from ..tracing.manager import TraceManager
from ..services.agent_selector import AgentSelector

if TYPE_CHECKING:
    from sentientresearchagent.hierarchical_agent_framework.graph.task_graph import TaskGraph

MAX_REPLAN_ATTEMPTS = 1

class ProcessingStage(BaseModel):
    """Represents a stage in the node processing pipeline."""
    stage_name: str
    model_info: Optional[Dict[str, Any]] = None
    status: str

    model_config = ConfigDict(protected_namespaces=())

class ProcessorContext:
    """Holds shared resources and configurations for node handlers."""
    def __init__(self,
                 task_graph: "TaskGraph",
                 knowledge_store: KnowledgeStore,
                 agent_registry: AgentRegistry,
                 config: NodeProcessorConfig,
                 hitl_coordinator: HITLCoordinator,
                 sub_node_creator: SubNodeCreator,
                 node_atomizer: NodeAtomizer,
                 trace_manager: TraceManager,
                 current_agent_blueprint: Optional[AgentBlueprint] = None,
                 update_callback: Optional[callable] = None,
                 update_manager: Optional[Any] = None,
                 context_builder: Optional[Any] = None):
        self.task_graph = task_graph
        self.knowledge_store = knowledge_store
        self.agent_registry = agent_registry
        self.config = config
        self.hitl_coordinator = hitl_coordinator
        self.sub_node_creator = sub_node_creator
        self.node_atomizer = node_atomizer
        self.trace_manager = trace_manager
        self.current_agent_blueprint = current_agent_blueprint
        self.update_callback = update_callback
        self.update_manager = update_manager
        self.context_builder = context_builder

class NodeProcessor:
    """
    Orchestrates the processing of a TaskNode by delegating to appropriate handlers
    based on the node's status and type.
    """
    def __init__(self,
                 task_graph: "TaskGraph",
                 knowledge_store: KnowledgeStore,
                 agent_registry: AgentRegistry,
                 trace_manager: TraceManager,
                 config: Optional[SentientConfig] = None,
                 node_processor_config: Optional[NodeProcessorConfig] = None,
                 agent_blueprint_name: Optional[str] = None,
                 agent_blueprint: Optional[AgentBlueprint] = None,
                 update_callback: Optional[callable] = None,
                 update_manager: Optional[Any] = None,
                 context_builder: Optional[Any] = None):
        logger.info("NodeProcessor initialized.")
        
        self.config = config or SentientConfig()
        self.node_processor_config = node_processor_config if node_processor_config else NodeProcessorConfig()
        self.update_callback = update_callback
        
        self.task_graph = task_graph
        self.knowledge_store = knowledge_store
        self.agent_registry = agent_registry
        self.trace_manager = trace_manager
        self.update_manager = update_manager
        self.context_builder = context_builder
        
        active_blueprint: Optional[AgentBlueprint] = None
        
        if agent_blueprint:
            active_blueprint = agent_blueprint
            logger.info(f"NodeProcessor will use provided Agent Blueprint: {active_blueprint.name}")
        elif agent_blueprint_name:
            active_blueprint = get_blueprint_by_name(agent_blueprint_name)
            if active_blueprint:
                logger.info(f"NodeProcessor will use Agent Blueprint: {active_blueprint.name}")
            else:
                logger.warning(f"Agent Blueprint '{agent_blueprint_name}' not found. NodeProcessor will operate without a specific blueprint.")
        else:
            logger.info("NodeProcessor initialized without a specific Agent Blueprint.")

        self.hitl_coordinator = HITLCoordinator(self.node_processor_config)
        self.sub_node_creator = SubNodeCreator(task_graph, knowledge_store)
        self.node_atomizer = NodeAtomizer(self.hitl_coordinator)

        self.processor_context = ProcessorContext(
            task_graph=self.task_graph,
            knowledge_store=self.knowledge_store,
            agent_registry=self.agent_registry,
            config=self.node_processor_config,
            hitl_coordinator=self.hitl_coordinator,
            sub_node_creator=self.sub_node_creator,
            node_atomizer=self.node_atomizer,
            trace_manager=self.trace_manager,
            current_agent_blueprint=active_blueprint,
            update_callback=self.update_callback,
            update_manager=self.update_manager,
            context_builder=self.context_builder
        )

        from sentientresearchagent.hierarchical_agent_framework.services import AgentSelector, ContextBuilderService
        from sentientresearchagent.hierarchical_agent_framework.orchestration.state_transition_manager import StateTransitionManager
        
        state_manager = StateTransitionManager(self.task_graph, knowledge_store)
        agent_selector = AgentSelector(blueprint=active_blueprint)
        if self.context_builder is None:
            context_builder = ContextBuilderService()
        else:
            context_builder = self.context_builder
        
        hitl_service = None
        
        self.handler_context = HandlerContext(
            knowledge_store=knowledge_store,
            agent_registry=agent_registry,
            state_manager=state_manager,
            agent_selector=agent_selector,
            context_builder=context_builder,
            hitl_service=hitl_service,
            trace_manager=trace_manager,
            config=config.dict() if hasattr(config, 'dict') else config,
            task_graph=task_graph,
            update_callback=update_callback
        )
        
        self.handler_strategies: Dict[TaskStatus, Any] = {
            TaskStatus.READY: ReadyNodeHandler(),
            TaskStatus.AGGREGATING: AggregatingNodeHandler(),
            TaskStatus.NEEDS_REPLAN: NeedsReplanNodeHandler()
        }
        logger.info(f"NodeProcessor initialized with handlers for statuses: {list(self.handler_strategies.keys())}")

    async def process_node(self, node: TaskNode, task_graph: "TaskGraph", knowledge_store: KnowledgeStore, update_manager=None):
        from sentientresearchagent.core.project_context import set_project_context
        set_project_context(self.trace_manager.project_id)
        
        self.processor_context.task_graph = task_graph
        self.processor_context.knowledge_store = knowledge_store
        self.processor_context.update_manager = update_manager
        
        original_status = node.status
        logger.info(f"NodeProcessor: Processing node {node.task_id} (Status: {node.status.name}, Type: {node.node_type}, Goal: '{node.goal[:30]}...')")
        
        # NEW: Debug goal override - force DebuggerAgent if goal contains 'debug'
        debug_forced = False
        if (node.status == TaskStatus.READY and 
            'debug' in node.goal.lower() and 
            node.node_type == NodeType.PLAN):  # Target initial planning phase
            node.agent_name = "DebuggerAgent"  # Use named registry lookup
            node.node_type = NodeType.EXECUTE  # Skip plan/atomize, go direct to execute
            logger.info(f"🔧 DEBUG OVERRIDE: Forcing {node.task_id} to DebuggerAgent (executor mode)")
            debug_forced = True
        
        self.trace_manager.create_trace(node.task_id, node.goal)
        
        # UPDATED: Conditional handler selection with debug override
        if debug_forced:
            # Force ExecuteHandler for debug (even if READY/PLAN originally)
            from sentientresearchagent.hierarchical_agent_framework.node_handlers import ExecuteHandler
            handler = ExecuteHandler()
            logger.info(f"NodeProcessor: Debug-forced dispatch to ExecuteHandler for {node.task_id}")
        else:
            handler = self.handler_strategies.get(node.status)
        
        if handler:
            try:
                self.handler_context.knowledge_store = knowledge_store
                self.handler_context.task_graph = task_graph
                await handler.handle(node, self.handler_context)
            except Exception as e:
                logger.exception(f"Node {node.task_id}: Unhandled exception in {handler.__class__.__name__}: {e}")
                if node.status not in [TaskStatus.FAILED, TaskStatus.CANCELLED]:
                    node.update_status(TaskStatus.FAILED, error_msg=f"Error in {handler.__class__.__name__}: {str(e)}")
        else:
            logger.warning(f"Node {node.task_id}: No specific handler for status {node.status.name}. Node will not be processed further in this cycle unless status changes.")

        if node.status == TaskStatus.PLAN_DONE and node.result and hasattr(node.result, 'sub_tasks'):
            logger.info(f"Node {node.task_id} completed planning - creating sub-nodes")
            plan_output = node.result
            if plan_output.sub_tasks:
                created_nodes = self.sub_node_creator.create_sub_nodes(node, plan_output)
                logger.info(f"Created {len(created_nodes)} sub-nodes for {node.task_id}")
                
                for sub_node in created_nodes:
                    depends_on = sub_node.aux_data.get('depends_on_indices', []) if sub_node.aux_data is not None else []
                    if not depends_on:
                        sub_node.update_status(TaskStatus.READY, validate_transition=True, update_manager=update_manager)
                        self.knowledge_store.add_or_update_record_from_node(sub_node)
                        logger.info(f"Transitioned sub-node {sub_node.task_id} to READY (no dependencies)")
        
        if node.status != original_status or node.result is not None or node.error is not None:
            logger.info(f"Node {node.task_id} status changed from {original_status} to {node.status} or has new results/errors. Updating knowledge store.")
        
        if hasattr(self.knowledge_store, 'add_or_update_record_from_node'):
            if self.knowledge_store.__class__.__name__ == 'OptimizedKnowledgeStore':
                immediate = update_manager is None or getattr(update_manager, 'execution_strategy', None) != 'deferred'
                self.knowledge_store.add_or_update_record_from_node(node, immediate=immediate)
            else:
                self.knowledge_store.add_or_update_record_from_node(node)
        
        logger.info(f"NodeProcessor: Finished processing for node {node.task_id}. Final status: {node.status.name}")