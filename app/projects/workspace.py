"""
KazmaAI Project Workspace Module

Provides:
- Project-centric context tracking
- File tree management
- Task history and state persistence
- Project templates
- Auto-save functionality
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.storage.base import BaseStorageManager
from core.events import EventBus, EventType, project_event


@dataclass
class Task:
    """A single task within a project."""
    
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    status: str = "pending"  # pending, in_progress, completed, cancelled
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "content": self.content,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        return cls(
            task_id=data.get("task_id", str(uuid.uuid4())),
            content=data.get("content", ""),
            status=data.get("status", "pending"),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.utcnow(),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            metadata=data.get("metadata", {}),
        )


@dataclass
class FileNode:
    """A file or directory in the project tree."""
    
    path: str
    is_directory: bool = False
    size: int = 0
    modified_at: Optional[datetime] = None
    language: Optional[str] = None  # Programming language
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "is_directory": self.is_directory,
            "size": self.size,
            "modified_at": self.modified_at.isoformat() if self.modified_at else None,
            "language": self.language,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileNode":
        return cls(
            path=data.get("path", ""),
            is_directory=data.get("is_directory", False),
            size=data.get("size", 0),
            modified_at=datetime.fromisoformat(data["modified_at"]) if data.get("modified_at") else None,
            language=data.get("language"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Project:
    """A project in KazmaAI."""
    
    project_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    status: str = "active"  # active, archived, deleted
    template: str = "default"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    # Project state
    tasks: List[Task] = field(default_factory=list)
    file_tree: List[FileNode] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    tags: List[str] = field(default_factory=list)
    language: str = "auto"  # Primary language (ar, en, auto)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "template": self.template,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tasks": [t.to_dict() for t in self.tasks],
            "file_tree": [f.to_dict() for f in self.file_tree],
            "context": self.context,
            "tags": self.tags,
            "language": self.language,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Project":
        return cls(
            project_id=data.get("project_id", str(uuid.uuid4())),
            name=data.get("name", ""),
            description=data.get("description", ""),
            status=data.get("status", "active"),
            template=data.get("template", "default"),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.utcnow(),
            tasks=[Task.from_dict(t) for t in data.get("tasks", [])],
            file_tree=[FileNode.from_dict(f) for f in data.get("file_tree", [])],
            context=data.get("context", {}),
            tags=data.get("tags", []),
            language=data.get("language", "auto"),
        )


class ProjectWorkspace:
    """
    Project-centric workspace manager for KazmaAI.
    
    Features:
    - Create, update, delete projects
    - Task management within projects
    - File tree tracking
    - Context persistence
    - Auto-save with configurable interval
    - Project templates
    """
    
    def __init__(self, storage_manager: BaseStorageManager, event_bus: Optional[EventBus] = None):
        """
        Initialize project workspace.
        
        Args:
            storage_manager: Storage backend for persistence
            event_bus: Optional event bus for broadcasting changes
        """
        self._storage = storage_manager
        self._event_bus = event_bus
        self._projects: Dict[str, Project] = {}
        self._auto_save_interval = storage_manager.config.get('projects', {}).get('auto_save_interval', 300)
        self._templates_path = Path(storage_manager.root) / storage_manager.config.get('projects', {}).get('templates_path', 'config/project_templates')
        
        # Load existing projects
        self._load_projects()
    
    def _load_projects(self) -> None:
        """Load all projects from storage."""
        project_ids = self._storage.list_keys(collection="projects")
        
        for project_id in project_ids:
            project_data = self._storage.retrieve(project_id, collection="projects")
            if project_data:
                project = Project.from_dict(project_data)
                self._projects[project_id] = project
    
    # =========================================================================
    # PROJECT MANAGEMENT
    # =========================================================================
    
    def create_project(
        self,
        name: str,
        description: str = "",
        template: str = "default",
        language: str = "auto",
        **context,
    ) -> Project:
        """
        Create a new project.
        
        Args:
            name: Project name
            description: Project description
            template: Template to use (default, python, web, etc.)
            language: Primary language (ar, en, auto)
            **context: Additional context data
            
        Returns:
            Created project
        """
        project = Project(
            name=name,
            description=description,
            template=template,
            language=language,
            context=context,
        )
        
        # Apply template if exists
        template_data = self._load_template(template)
        if template_data:
            self._apply_template(project, template_data)
        
        # Save project
        self._save_project(project)
        
        # Emit event
        if self._event_bus:
            self._event_bus.publish(project_event(
                EventType.PROJECT_CREATED,
                project_id=project.project_id,
                name=project.name,
                language=project.language,
            ))
        
        return project
    
    def get_project(self, project_id: str) -> Optional[Project]:
        """Get a project by ID."""
        return self._projects.get(project_id)
    
    def list_projects(self, status: Optional[str] = None) -> List[Project]:
        """
        List all projects.
        
        Args:
            status: Optional filter by status (active, archived, deleted)
            
        Returns:
            List of projects
        """
        projects = list(self._projects.values())
        
        if status:
            projects = [p for p in projects if p.status == status]
        
        return sorted(projects, key=lambda p: p.updated_at, reverse=True)
    
    def update_project(self, project: Project) -> None:
        """Update an existing project."""
        project.updated_at = datetime.utcnow()
        self._save_project(project)
        
        if self._event_bus:
            self._event_bus.publish(project_event(
                EventType.PROJECT_UPDATED,
                project_id=project.project_id,
                name=project.name,
            ))
    
    def delete_project(self, project_id: str) -> bool:
        """
        Delete a project.
        
        Args:
            project_id: Project ID to delete
            
        Returns:
            True if deleted, False if not found
        """
        if project_id not in self._projects:
            return False
        
        project = self._projects[project_id]
        project.status = "deleted"
        self._save_project(project)
        
        # Remove from memory
        del self._projects[project_id]
        
        # Emit event
        if self._event_bus:
            self._event_bus.publish(project_event(
                EventType.PROJECT_DELETED,
                project_id=project_id,
                name=project.name,
            ))
        
        return True
    
    def archive_project(self, project_id: str) -> bool:
        """Archive a project."""
        project = self._projects.get(project_id)
        if not project:
            return False
        
        project.status = "archived"
        self.update_project(project)
        return True
    
    # =========================================================================
    # TASK MANAGEMENT
    # =========================================================================
    
    def add_task(self, project_id: str, content: str, **metadata) -> Task:
        """
        Add a task to a project.
        
        Args:
            project_id: Project ID
            content: Task description
            **metadata: Additional task metadata
            
        Returns:
            Created task
        """
        project = self._projects.get(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")
        
        task = Task(content=content, metadata=metadata)
        project.tasks.append(task)
        
        self.update_project(project)
        
        if self._event_bus:
            self._event_bus.publish(project_event(
                EventType.TASK_ADDED,
                project_id=project_id,
                task_id=task.task_id,
                content=content,
            ))
        
        return task
    
    def update_task_status(self, project_id: str, task_id: str, status: str) -> bool:
        """
        Update task status.
        
        Args:
            project_id: Project ID
            task_id: Task ID
            status: New status (pending, in_progress, completed, cancelled)
            
        Returns:
            True if updated, False if not found
        """
        project = self._projects.get(project_id)
        if not project:
            return False
        
        for task in project.tasks:
            if task.task_id == task_id:
                task.status = status
                if status == "completed" and not task.completed_at:
                    task.completed_at = datetime.utcnow()
                elif status != "completed":
                    task.completed_at = None
                
                self.update_project(project)
                
                if self._event_bus and status == "completed":
                    self._event_bus.publish(project_event(
                        EventType.TASK_COMPLETED,
                        project_id=project_id,
                        task_id=task_id,
                    ))
                
                return True
        
        return False
    
    def get_tasks(self, project_id: str, status: Optional[str] = None) -> List[Task]:
        """Get tasks for a project."""
        project = self._projects.get(project_id)
        if not project:
            return []
        
        tasks = project.tasks
        if status:
            tasks = [t for t in tasks if t.status == status]
        
        return tasks
    
    # =========================================================================
    # FILE TREE MANAGEMENT
    # =========================================================================
    
    def update_file_tree(self, project_id: str, file_nodes: List[FileNode]) -> None:
        """
        Update the file tree for a project.
        
        Args:
            project_id: Project ID
            file_nodes: List of file/directory nodes
        """
        project = self._projects.get(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")
        
        project.file_tree = file_nodes
        self.update_project(project)
    
    def add_file_to_tree(self, project_id: str, file_node: FileNode) -> None:
        """Add a file to the project tree."""
        project = self._projects.get(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")
        
        project.file_tree.append(file_node)
        self.update_project(project)
    
    # =========================================================================
    # CONTEXT MANAGEMENT
    # =========================================================================
    
    def update_context(self, project_id: str, **context_updates) -> None:
        """Update project context."""
        project = self._projects.get(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")
        
        project.context.update(context_updates)
        self.update_project(project)
    
    def get_context(self, project_id: str, key: Optional[str] = None) -> Any:
        """Get project context, optionally filtered by key."""
        project = self._projects.get(project_id)
        if not project:
            return None
        
        if key:
            return project.context.get(key)
        return project.context
    
    # =========================================================================
    # TEMPLATE MANAGEMENT
    # =========================================================================
    
    def _load_template(self, template_name: str) -> Optional[Dict[str, Any]]:
        """Load a project template."""
        template_file = self._templates_path / f"{template_name}.yaml"
        
        if not template_file.exists():
            return None
        
        import yaml
        
        with open(template_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _apply_template(self, project: Project, template_data: Dict[str, Any]) -> None:
        """Apply a template to a project."""
        # Apply default tasks from template
        if "tasks" in template_data:
            for task_data in template_data["tasks"]:
                task = Task.from_dict(task_data)
                project.tasks.append(task)
        
        # Apply default file structure
        if "structure" in template_data:
            for item in template_data["structure"]:
                node = FileNode(
                    path=item if isinstance(item, str) else item.get("path", ""),
                    is_directory=item.get("is_directory", True) if isinstance(item, dict) else True,
                )
                project.file_tree.append(node)
        
        # Apply default context
        if "context" in template_data:
            project.context.update(template_data["context"])
    
    def list_templates(self) -> List[str]:
        """List available project templates."""
        if not self._templates_path.exists():
            return []
        
        return [f.stem for f in self._templates_path.glob("*.yaml")]
    
    # =========================================================================
    # PERSISTENCE
    # =========================================================================
    
    def _save_project(self, project: Project) -> None:
        """Save project to storage."""
        self._storage.store(
            project.project_id,
            project.to_dict(),
            collection="projects",
        )
        self._projects[project.project_id] = project
    
    def get_stats(self) -> Dict[str, Any]:
        """Get workspace statistics."""
        projects = list(self._projects.values())
        
        return {
            "total_projects": len(projects),
            "active_projects": len([p for p in projects if p.status == "active"]),
            "archived_projects": len([p for p in projects if p.status == "archived"]),
            "total_tasks": sum(len(p.tasks) for p in projects),
            "completed_tasks": sum(len([t for t in p.tasks if t.status == "completed"]) for p in projects),
            "templates_available": len(self.list_templates()),
        }