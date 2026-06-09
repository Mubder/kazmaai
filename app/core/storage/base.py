"""
BaseStorageManager - Abstract Base Class for KazmaAI

Provides:
- Self-discovery of agent root directory via .agent_root marker
- Infrastructure abstraction via pathlib (cross-platform)
- Pluggable backend interface (SQLite, JSON, VectorDB)
- Automatic directory initialization
- Unified configuration loading
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
import os


class StorageError(Exception):
    """Raised when storage operations fail."""
    pass


class BaseStorageManager(ABC):
    """
    Abstract base class for all storage backends in the KazmaAI.
    
    Subclasses must implement:
    - _connect(): Initialize backend connection
    - _disconnect(): Clean shutdown
    - store(): Write data
    - retrieve(): Read data
    - delete(): Remove data
    - list_keys(): Enumerate stored keys
    
    Features:
    - Self-discovers agent root from .agent_root marker
    - Initializes all required directories automatically
    - Loads unified config.yaml with environment variable interpolation
    """
    
    REQUIRED_DIRS = [
        "data/memory/vectors",
        "data/memory/conversations",
        "data/memory/summaries",
        "data/projects",
        "data/cache",
        "data/backups",
        "config/project_templates",
        "logs",
        "models",
    ]
    
    def __init__(self, explicit_root: Optional[Path] = None):
        """
        Initialize storage manager with automatic root discovery.
        
        Args:
            explicit_root: Optional explicit path to agent root.
                          If None, discovers root via .agent_root marker.
        """
        self._root = self._discover_root(explicit_root)
        self._config: Optional[Dict[str, Any]] = None
        self._initialized = False
        
        # Initialize directory structure
        self._init_directories()
        
        # Load configuration (lazy - on first access)
        self._config_loaded = False
        
        # Connect to backend
        self._connect()
        self._initialized = True
    
    @property
    def root(self) -> Path:
        """Agent root directory (read-only)."""
        return self._root
    
    @property
    def data_dir(self) -> Path:
        """Data directory path."""
        return self._root / "data"
    
    @property
    def config(self) -> Dict[str, Any]:
        """Loaded configuration (lazy load, read-only)."""
        if not self._config_loaded:
            self._config = self._load_config()
            self._config_loaded = True
        return self._config
    
    # =========================================================================
    # ROOT DISCOVERY
    # =========================================================================
    
    def _discover_root(self, explicit_root: Optional[Path] = None) -> Path:
        """
        Discover agent root directory by searching for .agent_root marker.
        
        Search strategy:
        1. If explicit_root provided and contains .agent_root, use it
        2. Search from current working directory upward for .agent_root
        3. Fall back to directory containing this file (if in app/)
        
        Args:
            explicit_root: Optional explicit path to agent root
            
        Returns:
            Path to agent root directory
            
        Raises:
            StorageError: If root cannot be discovered
        """
        # Strategy 1: Explicit root provided
        if explicit_root:
            explicit_root = Path(explicit_root).resolve()
            if (explicit_root / ".agent_root").exists():
                return explicit_root
            raise StorageError(
                f"Explicit root path provided but .agent_root marker not found: {explicit_root}"
            )
        
        # Strategy 2: Search upward from CWD
        current = Path.cwd()
        for parent in [current] + list(current.parents):
            if (parent / ".agent_root").exists():
                return parent
        
        # Strategy 3: Search from script location (assuming app/bootstrap.py)
        import inspect
        frame = inspect.currentframe()
        try:
            script_path = Path(inspect.getfile(frame)).resolve()
            script_dir = script_path.parent
            
            # Search upward from script directory
            for parent in [script_dir] + list(script_dir.parents):
                if (parent / ".agent_root").exists():
                    return parent
                
                # Also check if we're in app/ and root is parent
                if script_dir.name == "app" and (parent / ".agent_root").exists():
                    return parent
        finally:
            del frame
        
        # Strategy 4: Check common installation locations
        home = Path.home()
        candidates = [
            home / "kazmaai",
            home / ".kazmaai",
            Path("/opt/kazmaai"),
        ]
        
        for candidate in candidates:
            if candidate.exists() and (candidate / ".agent_root").exists():
                return candidate
        
        raise StorageError(
            "Cannot discover agent root: .agent_root marker not found.\n"
            "Run 'python app/bootstrap.py init' to initialize the agent,"
            "or ensure you're running from within the agent directory."
        )
    
    # =========================================================================
    # CONFIGURATION LOADING
    # =========================================================================
    
    def _load_config(self) -> Dict[str, Any]:
        """
        Load unified configuration from config/config.yaml.
        
        Features:
        - Environment variable interpolation: ${VAR_NAME} or ${VAR:-default}
        - Recursive merging with defaults
        - Cross-platform path normalization
        
        Returns:
            Configuration dictionary with all defaults applied
            
        Raises:
            StorageError: If config file not found or invalid
        """
        try:
            import yaml
        except ImportError:
            raise StorageError("PyYAML required: pip install pyyaml")
        
        config_file = self._root / "config" / "config.yaml"
        
        if not config_file.exists():
            raise StorageError(
                f"Configuration file not found: {config_file}\n"
                "Copy config/config.yaml.example to config/config.yaml and configure."
            )
        
        with open(config_file, 'r', encoding='utf-8') as f:
            raw_config = yaml.safe_load(f)
        
        # Interpolate environment variables
        config = self._interpolate_env(raw_config)
        
        # Merge with defaults
        defaults = self._get_config_defaults()
        config = self._merge_dicts(defaults, config)
        
        # Normalize all paths to be relative to agent root
        self._normalize_paths(config)
        
        return config
    
    def _interpolate_env(self, config: Any) -> Any:
        """
        Recursively interpolate environment variables in config values.
        
        Supports:
        - ${VAR_NAME} - replaced with env var, empty if not set
        - ${VAR_NAME:-default} - replaced with env var, or default if not set
        - ${VAR_NAME:default} - replaced with env var, or default if empty
        
        Args:
            config: Configuration dict/list/value
            
        Returns:
            Config with all ${...} patterns replaced
        """
        import re
        
        if isinstance(config, dict):
            return {k: self._interpolate_env(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self._interpolate_env(item) for item in config]
        elif isinstance(config, str):
            # Pattern: ${VAR:-default} or ${VAR:default} or ${VAR}
            pattern = r'\$\{([^}:]+)(?::-([^}]*))?\}'
            
            def replace(match):
                var_name = match.group(1)
                default = match.group(2)
                
                value = os.environ.get(var_name)
                
                if value is None:
                    # Variable not set
                    if default is not None:
                        return default
                    return ""
                elif value == "" and default is not None:
                    # Variable is empty string
                    return default
                else:
                    return value
            
            return re.sub(pattern, replace, config)
        else:
            return config
    
    def _get_config_defaults(self) -> Dict[str, Any]:
        """Return default configuration structure."""
        return {
            'agent': {
                'name': 'kazmaai',
                'version': '1.0.0',
            },
            'storage': {
                'backend': 'sqlite',
                'sqlite': {
                    'path': 'data/storage.db',
                    'journal_mode': 'WAL',
                    'timeout': 30,
                },
                'vector_backend': 'chromadb',
                'chromadb': {
                    'path': 'data/memory/vectors',
                    'anonymized_telemetry': False,
                },
            },
            'paths': {
                'data': 'data',
                'logs': 'logs',
                'backups': 'data/backups',
                'cache': 'data/cache',
                'projects': 'data/projects',
                'models': 'models',
            },
            'models': {
                'chat': {
                    'provider': 'ollama',
                    'model': 'llama3.1:8b',
                    'context_length': 8192,
                },
                'embedding': {
                    'provider': 'ollama',
                    'model': 'nomic-embed-text',
                },
            },
            'logging': {
                'level': 'INFO',
                'file': 'logs/orchestrator.log',
                'max_size_mb': 50,
                'backup_count': 5,
            },
            'backup': {
                'auto_backup': True,
                'retention': {
                    'max_backups': 10,
                    'max_age_days': 30,
                },
            },
            'telegram': {
                'enabled': False,
                'bot_token': '',
                'allowed_users': [],
            },
            'web': {
                'enabled': False,
                'host': '127.0.0.1',
                'port': 8080,
            },
        }
    
    def _merge_dicts(self, defaults: Dict, overrides: Dict) -> Dict:
        """Recursively merge configuration dictionaries."""
        result = defaults.copy()
        for key, value in overrides.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._merge_dicts(result[key], value)
            else:
                result[key] = value
        return result
    
    def _normalize_paths(self, config: Dict[str, Any]) -> None:
        """
        Normalize all path values to be relative to agent root.
        
        Converts string paths to Path objects and ensures they're relative.
        """
        # This is a no-op for now but provides a hook for future path validation
        pass
    
    # =========================================================================
    # DIRECTORY INITIALIZATION
    # =========================================================================
    
    def _init_directories(self) -> None:
        """
        Create all required directories if they don't exist.
        
        Called once during initialization. Safe to call multiple times.
        """
        for dir_path in self.REQUIRED_DIRS:
            full_path = self._root / dir_path
            full_path.mkdir(parents=True, exist_ok=True)
    
    # =========================================================================
    # BACKEND INTERFACE (Abstract Methods)
    # =========================================================================
    
    @abstractmethod
    def _connect(self) -> None:
        """
        Initialize backend connection.
        
        Called once during __init__. Implement in subclass.
        """
        pass
    
    @abstractmethod
    def _disconnect(self) -> None:
        """
        Clean shutdown of backend connection.
        
        Called on close() or destruction. Implement in subclass.
        """
        pass
    
    @abstractmethod
    def store(self, key: str, value: Any, collection: Optional[str] = None) -> bool:
        """
        Store data in the backend.
        
        Args:
            key: Unique identifier for the data
            value: Data to store (will be serialized appropriately)
            collection: Optional namespace/collection for grouping
            
        Returns:
            True on success, False on failure
            
        Raises:
            StorageError: On storage failure
        """
        pass
    
    @abstractmethod
    def retrieve(self, key: str, collection: Optional[str] = None) -> Optional[Any]:
        """
        Retrieve data from the backend.
        
        Args:
            key: Identifier for the data
            collection: Optional namespace/collection
            
        Returns:
            Stored value or None if not found
            
        Raises:
            StorageError: On retrieval failure
        """
        pass
    
    @abstractmethod
    def delete(self, key: str, collection: Optional[str] = None) -> bool:
        """
        Delete data from the backend.
        
        Args:
            key: Identifier for the data
            collection: Optional namespace/collection
            
        Returns:
            True if deleted, False if not found
            
        Raises:
            StorageError: On deletion failure
        """
        pass
    
    @abstractmethod
    def list_keys(self, collection: Optional[str] = None,
                  pattern: Optional[str] = None) -> List[str]:
        """
        List all keys in the backend.
        
        Args:
            collection: Optional namespace/collection
            pattern: Optional glob pattern for filtering (e.g., "project_*")
            
        Returns:
            List of key strings
            
        Raises:
            StorageError: On listing failure
        """
        pass
    
    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
    
    def close(self) -> None:
        """Explicitly close backend connection and cleanup."""
        if self._initialized:
            self._disconnect()
            self._initialized = False
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure cleanup."""
        self.close()
    
    def __del__(self):
        """Destructor - ensure cleanup."""
        if hasattr(self, '_initialized') and self._initialized:
            try:
                self.close()
            except Exception:
                pass  # Ignore errors during destruction
    
    # =========================================================================
    # SNAPSHOT/BACKUPPORT
    # =========================================================================
    
    def get_snapshot_path(self, name: Optional[str] = None) -> Path:
        """
        Get path for next snapshot archive.
        
        Args:
            name: Optional custom name for the snapshot
            
        Returns:
            Path: data/backups/YYYY-MM-DD_HHMMSS.zip (or custom name)
        """
        if name:
            return self.data_dir / "backups" / f"{name}.zip"
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        return self.data_dir / "backups" / f"{timestamp}.zip"
    
    def get_snapshot_directories(self) -> List[Path]:
        """
        Get all directories to include in a snapshot.
        
        Returns:
            List of absolute paths to backup
        """
        return [
            self.data_dir / "memory",
            self.data_dir / "projects",
            self._root / "config" / "config.yaml",
            self._root / "config" / "project_templates",
        ]
    
    def get_snapshot_exclude_patterns(self) -> List[str]:
        """
        Get patterns to exclude from snapshots.
        
        Returns:
            List of glob patterns to exclude
        """
        return [
            "data/cache/*",
            "logs/*.log",
            "**/__pycache__",
            "**/*.pyc",
            "**/*.pyo",
            ".git/*",
        ]
    
    # =========================================================================
    # PROJECT-SPECIFIC HELPERS
    # =========================================================================
    
    def get_project_path(self, project_id: str) -> Path:
        """
        Get path to a specific project directory.
        
        Args:
            project_id: Unique project identifier
            
        Returns:
            Path to project directory
        """
        project_dir = self.data_dir / "projects" / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir
    
    def get_memory_path(self, memory_type: str) -> Path:
        """
        Get path to a specific memory subdirectory.
        
        Args:
            memory_type: Type of memory (vectors, conversations, summaries)
            
        Returns:
            Path to memory directory
        """
        return self.data_dir / "memory" / memory_type