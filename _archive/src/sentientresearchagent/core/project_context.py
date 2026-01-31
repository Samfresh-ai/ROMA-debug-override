"""
Thread-Local Project Context Manager

Provides thread-safe project context isolation to prevent race conditions
when multiple projects run simultaneously.
"""

import threading
import os
from typing import Optional, Any, Dict
from loguru import logger
from enum import Enum
from datetime import datetime

from ..hierarchical_agent_framework.types import TaskStatus, TaskType, NodeType  # For deserialize enums
from ..hierarchical_agent_framework.node.task_node import TaskNode  # Absolute for load_state

class ProjectContextManager:
    """
    Thread-local project context manager that ensures each execution thread
    maintains its own isolated project ID context.
    
    This solves the race condition issue where multiple concurrent projects
    would overwrite each other's CURRENT_PROJECT_ID environment variable.
    """
    
    def __init__(self):
        self._context = threading.local()
    
    def set_project_id(self, project_id: str) -> None:
        """
        Set the project ID for the current thread.
        
        Args:
            project_id: The project ID to set for this thread
        """
        self._context.project_id = project_id
        logger.debug(f"Set project ID for thread {threading.get_ident()}: {project_id}")
    
    def get_project_id(self) -> Optional[str]:
        """
        Get the project ID for the current thread.
        
        Returns:
            The project ID for the current thread, or None if not set
        """
        if hasattr(self._context, 'project_id'):
            return self._context.project_id
        return None
    
    def clear_project_id(self) -> None:
        """
        Clear the project ID for the current thread.
        """
        if hasattr(self._context, 'project_id'):
            old_project_id = self._context.project_id
            delattr(self._context, 'project_id')
            logger.debug(f"Cleared project ID for thread {threading.get_ident()}: {old_project_id}")
    
    def get_project_directories(self) -> dict:
        """
        Get project-specific directory paths based on current project context.
        
        Returns:
            Dictionary containing project directory paths
        """
        project_id = self.get_project_id()
        if not project_id:
            return {}
            
        from .project_structure import ProjectStructure
        return ProjectStructure.get_project_directories(project_id)
    
    def is_project_context_set(self) -> bool:
        """
        Check if a project context is set for the current thread.
        
        Returns:
            True if project context is set, False otherwise
        """
        return hasattr(self._context, 'project_id')
    
    def get_context_info(self) -> dict:
        """
        Get debugging information about the current context.
        
        Returns:
            Dictionary with context debugging information
        """
        thread_id = threading.get_ident()
        thread_project_id = getattr(self._context, 'project_id', None)
        
        return {
            'thread_id': thread_id,
            'thread_project_id': thread_project_id,
            'effective_project_id': self.get_project_id(),
            'context_set': self.is_project_context_set()
        }

# Global instance for application-wide use
_project_context_manager = ProjectContextManager()

def set_project_context(project_id: str) -> None:
    """
    Set the project context for the current thread.
    
    Args:
        project_id: The project ID to set
    """
    _project_context_manager.set_project_id(project_id)

def get_project_context() -> Optional[str]:
    """
    Get the current project context for this thread.
    
    Returns:
        The current project ID or None if not set
    """
    return _project_context_manager.get_project_id()

def clear_project_context() -> None:
    """
    Clear the project context for the current thread.
    """
    _project_context_manager.clear_project_id()

def get_project_directories() -> dict:
    """
    Get project-specific directory paths.
    
    Returns:
        Dictionary containing project directories
    """
    return _project_context_manager.get_project_directories()

def is_project_context_set() -> bool:
    """
    Check if project context is set for current thread.
    
    Returns:
        True if context is set, False otherwise
    """
    return _project_context_manager.is_project_context_set()

def get_context_debug_info() -> dict:
    """
    Get debugging information about current project context.
    
    Returns:
        Dictionary with debugging information
    """
    return _project_context_manager.get_context_info()

class ProjectExecutionContext:
    # Assuming existing class definition here, adding the methods

    def serialize_value(self, value: Any) -> Any:
        """Recursive serialize for save_state."""
        if isinstance(value, Enum):
            return value.name  # 'DONE'
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {k: self.serialize_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.serialize_value(item) for item in value]
        return value

    def deserialize_value(self, value: Any) -> Any:
        """Recursive deserialize for load_state."""
        if isinstance(value, dict):
            deserialized = {k: self.deserialize_value(v) for k, v in value.items()}
            # Enums (status, task_type, etc.)
            enum_fields = ['status', 'task_type', 'node_type']  # Add more if needed
            for field in enum_fields:
                if field in deserialized and isinstance(deserialized[field], str):
                    try:
                        # Assume TaskStatus for status; adjust for others (e.g., TaskType[field.upper()])
                        if field == 'status':
                            deserialized[field] = TaskStatus[deserialized[field].upper()]
                        # Add elif for other enums
                        elif field == 'task_type':
                            deserialized[field] = TaskType[deserialized[field].upper()]
                        elif field == 'node_type':
                            deserialized[field] = NodeType[deserialized[field].upper()]
                    except (KeyError, ValueError):
                        deserialized[field] = getattr(TaskStatus, 'PENDING', None)  # Fallback
            # Timestamps
            ts_fields = ['timestamp_created', 'timestamp_updated', 'timestamp_completed']
            for field in ts_fields:
                if field in deserialized and isinstance(deserialized[field], str):
                    try:
                        deserialized[field] = datetime.fromisoformat(deserialized[field])
                    except ValueError:
                        deserialized[field] = None
            return deserialized
        if isinstance(value, list):
            return [self.deserialize_value(item) for item in value]
        return value

    def save_state(self) -> Dict[str, Any]:
        try:
            raw_data = self.task_graph.to_visualization_dict() if hasattr(self.task_graph, 'to_visualization_dict') else {}
            return self.serialize_value(raw_data)  # Recursive serialize
        except Exception as e:
            logger.error(f"Failed to save state for {self.project_id}: {e}")
            return {}

    def load_state(self, project_state: Dict[str, Any]) -> bool:
        try:
            # Deserialize first
            deserialized_state = self.deserialize_value(project_state)
            
            # Clear existing
            self.task_graph.nodes.clear()
            self.task_graph.graphs.clear()
            self.knowledge_store.clear()
            
            if 'all_nodes' in deserialized_state:
                from .task_node import TaskNode  # Adjust import
                for node_id, node_data in deserialized_state['all_nodes'].items():
                    try:
                        # node_data now has proper enums/datetime
                        task_node = TaskNode(**node_data)
                        self.task_graph.nodes[node_id] = task_node
                        self.knowledge_store.add_or_update_record_from_node(task_node)
                    except Exception as e:
                        logger.warning(f"Failed node {node_id}: {e}")
                        continue
            
            # Reconstruct graphs (existing code)
            if 'graphs' in deserialized_state:
                self._reconstruct_graphs(deserialized_state['graphs'])
            
            self.task_graph.overall_project_goal = deserialized_state.get('overall_project_goal')
            self.task_graph.root_graph_id = deserialized_state.get('root_graph_id')
            
            logger.info(f"✅ Loaded {len(self.task_graph.nodes)} nodes for {self.project_id}")
            return True
        except Exception as e:
            logger.error(f"Load failed for {self.project_id}: {e}")
            return False