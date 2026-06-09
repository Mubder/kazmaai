"""
KazmaAI - Bootstrap Module

Provides:
- Agent initialization and setup
- Root discovery verification
- Configuration validation
- First-run wizard
- Snapshot/backup operations
"""

import sys
import zipfile
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, List


def verify_root(root_path: Optional[Path] = None) -> Path:
    """
    Verify agent root directory is valid.
    
    Args:
        root_path: Optional explicit root path
        
    Returns:
        Verified root path
        
    Raises:
        RuntimeError: If root is invalid
    """
    if root_path:
        root_path = Path(root_path).resolve()
    else:
        root_path = Path(__file__).parent.parent.parent
    
    marker = root_path / ".agent_root"
    
    if not marker.exists():
        raise RuntimeError(
            f"Not a valid KazmaAI installation: {root_path}\n"
            ".agent_root marker not found. Run 'python app/bootstrap.py init' first."
        )
    
    # Verify critical directories
    required = ["app", "data", "config"]
    missing = [d for d in required if not (root_path / d).exists()]
    
    if missing:
        raise RuntimeError(
            f"Incomplete installation. Missing directories: {', '.join(missing)}\n"
            "Run 'python app/bootstrap.py init' to complete setup."
        )
    
    return root_path


def initialize_agent(root_path: Optional[Path] = None, interactive: bool = True) -> bool:
    """
    Initialize agent installation.
    
    Creates:
    - .agent_root marker
    - Required directory structure
    - config.yaml from example (if not exists)
    - .env file from example (if not exists)
    
    Args:
        root_path: Optional explicit root path
        interactive: If True, prompt user for configuration
        
    Returns:
        True on success, False on failure
    """
    if root_path:
        root_path = Path(root_path).resolve()
    else:
        root_path = Path(__file__).parent.parent.parent
    
    print(f"🚀 Initializing KazmaAI at: {root_path}")
    
    # Create marker file
    marker = root_path / ".agent_root"
    if not marker.exists():
        marker.write_text(
            f"# KazmaAI - Agent Root Marker\n"
            f"# Created: {datetime.now().isoformat()}\n"
            f"# Version: 1.0.0\n"
        )
        print("  ✓ Created .agent_root marker")
    
    # Create required directories
    required_dirs = [
        "app/core/storage",
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
    
    for dir_path in required_dirs:
        full_path = root_path / dir_path
        if not full_path.exists():
            full_path.mkdir(parents=True, exist_ok=True)
            print(f"  ✓ Created directory: {dir_path}")
    
    # Create config.yaml if not exists
    config_src = root_path / "config" / "config.yaml"
    config_example = root_path / "config" / "config.yaml.example"
    
    if not config_src.exists():
        if config_example.exists():
            shutil.copy(config_example, config_src)
            print("  ✓ Created config.yaml from example")
        else:
            print("  ⚠ config.yaml.example not found - create config.yaml manually")
    
    # Create .env if not exists
    env_file = root_path / ".env"
    env_example = root_path / ".env.example"
    
    if not env_file.exists() and env_example.exists():
        shutil.copy(env_example, env_file)
        print("  ✓ Created .env from example")
    
    # Create default project template
    template_path = root_path / "config" / "project_templates" / "default.yaml"
    if not template_path.exists():
        template_path.write_text(
            "# Default Project Template\n"
            "name: default\n"
            "description: Default project configuration\n"
            "structure:\n"
            "  - src/\n"
            "  - tests/\n"
            "  - docs/\n"
        )
        print("  ✓ Created default project template")
    
    print("\n✅ Initialization complete!")
    print("\nNext steps:")
    print("  1. Edit config/config.yaml to configure your agent")
    print("  2. Copy .env.example to .env and set your API keys")
    print("  3. Run: python app/main.py")
    
    return True


def create_snapshot(
    root_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    include_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
) -> Path:
    """
    Create a snapshot backup of the agent state.
    
    Args:
        root_path: Agent root directory (auto-discovered if None)
        output_path: Output ZIP file path (auto-generated if None)
        include_patterns: Directories to include (uses defaults if None)
        exclude_patterns: Patterns to exclude (uses defaults if None)
        
    Returns:
        Path to created snapshot file
    """
    if root_path is None:
        root_path = verify_root()
    else:
        root_path = Path(root_path).resolve()
        verify_root(root_path)
    
    # Default include patterns
    if include_patterns is None:
        include_patterns = [
            "data/memory",
            "data/projects",
            "config/config.yaml",
            "config/project_templates",
        ]
    
    # Default exclude patterns
    if exclude_patterns is None:
        exclude_patterns = [
            "data/cache/*",
            "data/storage.db-wal",
            "data/storage.db-shm",
            "logs/*.log",
            "**/__pycache__",
            "**/*.pyc",
            "**/*.pyo",
            ".git/*",
        ]
    
    # Generate output path if not specified
    if output_path is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_path = root_path / "data" / "backups" / f"{timestamp}.zip"
    else:
        output_path = Path(output_path).resolve()
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"📦 Creating snapshot: {output_path}")
    
    # Collect files to include
    files_to_add = []
    
    for pattern in include_patterns:
        src_path = root_path / pattern
        
        if src_path.is_file():
            files_to_add.append((src_path, pattern))
        elif src_path.is_dir():
            for file_path in src_path.rglob("*"):
                if file_path.is_file():
                    # Check exclude patterns
                    relative = file_path.relative_to(root_path)
                    relative_str = str(relative)
                    
                    excluded = False
                    for exclude in exclude_patterns:
                        if relative_str.startswith(exclude.rstrip("*")):
                            excluded = True
                            break
                        if "*" in exclude:
                            import fnmatch
                            if fnmatch.fnmatch(relative_str, exclude):
                                excluded = True
                                break
                    
                    if not excluded:
                        files_to_add.append((file_path, relative_str))
    
    # Create ZIP archive
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path, arcname in files_to_add:
            zipf.write(file_path, arcname)
            print(f"  + {arcname}")
    
    print(f"\n✅ Snapshot created: {output_path}")
    print(f"   Size: {output_path.stat().st_size / 1024 / 1024:.2f} MB")
    
    return output_path


def restore_snapshot(
    snapshot_path: Path,
    target_path: Optional[Path] = None,
    overwrite: bool = False,
) -> Path:
    """
    Restore agent state from a snapshot.
    
    Args:
        snapshot_path: Path to snapshot ZIP file
        target_path: Restore destination (agent root, uses snapshot location if None)
        overwrite: If True, overwrite existing files
        
    Returns:
        Path to restored directory
    """
    snapshot_path = Path(snapshot_path).resolve()
    
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")
    
    if target_path is None:
        # Restore to same directory as snapshot
        target_path = snapshot_path.parent.parent
    else:
        target_path = Path(target_path).resolve()
    
    print(f"📥 Restoring snapshot: {snapshot_path}")
    print(f"   Target: {target_path}")
    
    if not overwrite and target_path.exists():
        confirm = input(f"⚠️  {target_path} exists. Overwrite? [y/N]: ")
        if confirm.lower() != 'y':
            print("Restore cancelled.")
            return target_path
    
    # Extract snapshot
    with zipfile.ZipFile(snapshot_path, 'r') as zipf:
        zipf.extractall(target_path)
    
    print(f"\n✅ Restore complete: {target_path}")
    print("\nNext steps:")
    print("  1. Verify config/config.yaml is correct for this system")
    print("  2. Update environment variables in .env if needed")
    print("  3. Run: python app/main.py")
    
    return target_path


def main():
    """CLI entry point for bootstrap operations."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="KazmaAI - Bootstrap & Maintenance"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize agent installation")
    init_parser.add_argument(
        "--path", type=Path, help="Agent root path (default: current directory)"
    )
    init_parser.add_argument(
        "--no-interactive", action="store_true", help="Skip interactive prompts"
    )
    
    # Snapshot command
    snapshot_parser = subparsers.add_parser("snapshot", help="Create backup snapshot")
    snapshot_parser.add_argument(
        "--path", type=Path, help="Agent root path (default: current directory)"
    )
    snapshot_parser.add_argument(
        "--output", type=Path, help="Output ZIP file path"
    )
    
    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore from snapshot")
    restore_parser.add_argument(
        "snapshot", type=Path, help="Snapshot ZIP file to restore"
    )
    restore_parser.add_argument(
        "--target", type=Path, help="Restore destination (default: snapshot location)"
    )
    restore_parser.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing files"
    )
    
    # Verify command
    verify_parser = subparsers.add_parser("verify", help="Verify installation")
    verify_parser.add_argument(
        "--path", type=Path, help="Agent root path (default: current directory)"
    )
    
    args = parser.parse_args()
    
    if args.command == "init":
        success = initialize_agent(
            root_path=args.path,
            interactive=not args.no_interactive,
        )
        sys.exit(0 if success else 1)
    
    elif args.command == "snapshot":
        try:
            snapshot_path = create_snapshot(
                root_path=args.path,
                output_path=args.output,
            )
            print(f"\nSnapshot saved: {snapshot_path}")
        except Exception as e:
            print(f"Error creating snapshot: {e}")
            sys.exit(1)
    
    elif args.command == "restore":
        try:
            restore_snapshot(
                snapshot_path=args.snapshot,
                target_path=args.target,
                overwrite=args.overwrite,
            )
        except Exception as e:
            print(f"Error restoring snapshot: {e}")
            sys.exit(1)
    
    elif args.command == "verify":
        try:
            root = verify_root(args.path)
            print(f"✅ Valid KazmaAI installation: {root}")
        except RuntimeError as e:
            print(f"❌ Invalid installation: {e}")
            sys.exit(1)
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()