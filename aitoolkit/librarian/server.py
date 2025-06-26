#!/usr/bin/env python3
"""
AI Librarian MCP Server

This is a standalone MCP server that implements the AI Librarian functionality,
providing code understanding and context maintenance across conversations.

Key Features:
- Code parsing and component tracking
- Project monitoring for changes
- Persistent context across conversations

Usage:
    python server.py [project_dir1] [project_dir2] ...
"""

# Configure MCP protocol timeouts - Must come before other imports
import os
os.environ["MCP_DEFAULT_TIMEOUT"] = "600000"  # 10 minutes (milliseconds)
os.environ["MCP_MAX_REQUEST_TIMEOUT"] = "1200000"  # 20 minutes (milliseconds)
os.environ["MCP_INITIALIZATION_TIMEOUT"] = "1800000"  # 30 minutes
os.environ["MCP_REGISTRATION_TIMEOUT"] = "900000"  # 15 minutes for tool registration
os.environ["MCP_LAZY_TOOL_REGISTRATION"] = "true"  # Enable lazy tool registration
os.environ["MCP_BATCH_TOOL_REGISTRATION"] = "true"  # Register tools in batches
os.environ["MCP_PROGRESSIVE_LOADING"] = "true"  # Load features progressively
os.environ["MCP_HEARTBEAT_INTERVAL"] = "5000"  # Send heartbeat every 5 seconds
import sys
import json
import time
import atexit
import logging
import threading
import ast
import os.path
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Set, Tuple, cast

# Add the current directory to sys.path to ensure local imports work
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Get the parent directory to import from aitoolkit
parent_dir = os.path.dirname(os.path.dirname(current_dir))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import dependencies with absolute paths to ensure consistency
from aitoolkit.librarian.todos import TodoManager
from aitoolkit.librarian.sanity_check_fixed import run_sanity_check
from aitoolkit.librarian.enhanced_indexer import initialize_enhanced_librarian
from aitoolkit.librarian.edit_bookmark import EditBookmark
from aitoolkit.utils.logging_manager import configure_logger

# Import Unified Context Integration
try:
    from aitoolkit.librarian.unified_context_integration import register_unified_context_tools
except ImportError:
    print("Unified Context Integration not available")

# Import TaskBoard Integration
try:
    from aitoolkit.librarian.server_taskboard_integration import apply_taskboard_integration
    from aitoolkit.librarian.task_board import (
        submit_background_task,
        get_task_status_mcp,
        get_task_result_mcp,
        cancel_task_mcp,
        list_tasks_mcp
    )
    # Import think tool from its dedicated module
    from aitoolkit.librarian.think_tool import think
    TASKBOARD_AVAILABLE = True
except ImportError as e:
    print(f"TaskBoard Integration not available: {e}")
    TASKBOARD_AVAILABLE = False
    register_unified_context_tools = None

# Import Security Analyzer Integration
try:
    from aitoolkit.librarian.security_analyzer_integration import apply_security_analyzer_integration
    SECURITY_ANALYZER_AVAILABLE = True
except ImportError:
    print("Security Analyzer Integration not available")
    SECURITY_ANALYZER_AVAILABLE = False

# Import MCP Extensions (prompts and resources)
try:
    from aitoolkit.librarian.mcp_extensions import register_mcp_extensions
    MCP_EXTENSIONS_AVAILABLE = True
except ImportError:
    print("MCP Extensions not available")
    MCP_EXTENSIONS_AVAILABLE = False

# Import Prompt Tools (tools that provide prompt-like guidance)
try:
    from aitoolkit.librarian.prompt_tools import register_prompt_like_tools
    PROMPT_TOOLS_AVAILABLE = True
except ImportError:
    print("Prompt Tools not available")
    PROMPT_TOOLS_AVAILABLE = False

# Import filesystem module for file operations
import shutil
import tempfile
import fnmatch
import mimetypes
from pathlib import Path

# Import datetime for timestamps
import datetime

# Import git tracker module
from aitoolkit.utils.git_tracker import (
    get_repository_status,
    get_commit_history,
    get_branches,
    get_tags,
    get_remotes,
    update_git_history_files
)

# Try different import paths for FastMCP
try:
    # First try the pip-installed mcp package
    from mcp.server.fastmcp import FastMCP, Context
    MCP_AVAILABLE = True
    print("[SUCCESS] MCP package found and imported successfully")
except ImportError:
    try:
        # Try to import from connector.py (which has an alternate implementation)
        from aitoolkit.mcp.connector import FastMCP, Context
        print("[SUCCESS] Using alternate MCP implementation from connector.py")
        MCP_AVAILABLE = True
    except ImportError:
        # Don't try to auto-install as it often fails in production environments
        print("[WARNING] MCP package not found.")
        print("[WARNING] Please install it manually with: pip install mcp[cli]")
        print("[WARNING] Limited functionality mode - Claude Desktop connection will not work.")
        raise ImportError("Could not import FastMCP. Please install the mcp package: pip install mcp[cli]")

# Configure logging using the centralized logging manager
logger = configure_logger(
    name="ai-librarian",
    log_level=logging.INFO,
    log_file="ai_librarian.log",
    log_dir=os.path.join(parent_dir, "logs"),
    console_level=logging.WARNING,
    file_level=logging.INFO
)

# Create the MCP server with proper initialization
mcp = FastMCP(
    "ai-librarian",
    capabilities={
        "resources": {"subscribe": True, "listChanged": True},
        "tools": {"listChanged": True},
        "prompts": {"listChanged": True}
    }
)

# Thread synchronization lock
state_lock = threading.Lock()

# Global context for AI Librarian
librarian_context = {
    "projects": {},  # Map of project paths to their librarian info
    "active_projects": set(),  # Set of currently monitored projects
    "last_update": {},  # Map of project paths to last update timestamp
    "indexed_files": {},  # Map of project paths to their indexed files
    "components": {},  # Map of project paths to their component registries
    "paused": False,   # Flag to temporarily pause monitoring
    "tool_index": None,  # Path to Tool Index directory if available
    "file_cache": {},  # Cache for frequently accessed files
    "cache_stats": {"hits": 0, "misses": 0},  # Statistics for cache performance
    "cache_max_size": 100,  # Maximum number of files to cache
    "cache_max_age": 60,  # Maximum age of cached files in seconds
    "git_info": {}  # Cache for git repository information
}

# File change monitoring thread
monitoring_active = True

def monitor_projects():
    """
    Monitor active projects for file changes and update the AI Librarian context.
    This runs in a separate thread to provide real-time updates.
    """
    logger.info("Starting project monitoring thread")
    
    # Initial delay to ensure server is fully initialized
    time.sleep(10)  # Wait 10 seconds before first check

    while monitoring_active:
        try:
            # Check if monitoring is paused
            with state_lock:
                if librarian_context["paused"]:
                    time.sleep(1)  # Short sleep when paused
                    continue

                current_time = time.time()
                # Make a copy of active projects to avoid modification during iteration
                active_projects = list(librarian_context["active_projects"])

            # Check each active project for changes
            for project_path in active_projects:
                if not os.path.exists(project_path):
                    with state_lock:
                        logger.warning(f"Project path no longer exists: {project_path}")
                        librarian_context["active_projects"].remove(project_path)
                    continue

                # Only check every 30 seconds per project to avoid excessive file system operations
                with state_lock:
                    last_check = librarian_context["last_update"].get(project_path, 0)

                if current_time - last_check < 30:
                    continue

                # Check for file changes
                has_changes = check_project_changes(project_path)
                if has_changes:
                    with state_lock:
                        logger.info(f"Changes detected in project: {project_path}")
                        update_librarian_for_project(project_path)
                        librarian_context["last_update"][project_path] = current_time
                else:
                    with state_lock:
                        librarian_context["last_update"][project_path] = current_time

            # Sleep to avoid high CPU usage
            time.sleep(5)
        except Exception as e:
            logger.error(f"Error in monitoring thread: {str(e)}")
            time.sleep(10)  # Sleep longer on error

def check_project_changes(project_path):
    """
    Check if a project has changes since the last update.
    
    Args:
        project_path: Path to the project root
        
    Returns:
        bool: True if changes detected, False otherwise
    """
    try:
        # Get currently indexed files
        with state_lock:
            indexed_files = librarian_context["indexed_files"].get(project_path, {})

        # Scan for Python files
        current_files = {}
        for root, _, files in os.walk(project_path):
            # Skip hidden directories and common excluded dirs
            if any(part.startswith('.') for part in Path(root).parts) or \
               any(part in ['venv', 'env', '__pycache__', 'node_modules'] for part in Path(root).parts):
                continue

            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    try:
                        mtime = os.path.getmtime(file_path)
                        current_files[file_path] = mtime
                    except OSError:
                        pass

        # Check for added, removed, or modified files
        if set(indexed_files.keys()) != set(current_files.keys()):
            return True

        # Check for modified files
        for file_path, mtime in current_files.items():
            if file_path in indexed_files and indexed_files[file_path] != mtime:
                return True

        return False
    except Exception as e:
        logger.error(f"Error checking project changes: {str(e)}")
        return False

def update_librarian_for_project(project_path):
    """
    Update the AI Librarian for a project.
    
    Args:
        project_path: Path to the project root
    """
    try:
        # Use the already imported enhanced_indexer module (imported at the top)
        # Update the librarian files using the imported function
        message, file_count, component_count = initialize_enhanced_librarian(project_path)
        logger.info(f"Updated librarian for {project_path}: {message}")

        # Update our in-memory representation
        ai_ref_path = os.path.join(project_path, ".ai_reference")

        # Read script index
        script_index_path = os.path.join(ai_ref_path, "script_index.json")
        if os.path.exists(script_index_path):
            with open(script_index_path, 'r', encoding='utf-8') as f:
                script_index = json.load(f)
                with state_lock:
                    librarian_context["projects"][project_path] = script_index

        # Read component registry
        component_registry_path = os.path.join(ai_ref_path, "component_registry.json")
        if os.path.exists(component_registry_path):
            with open(component_registry_path, 'r', encoding='utf-8') as f:
                component_registry = json.load(f)
                with state_lock:
                    librarian_context["components"][project_path] = component_registry

        # Update indexed files
        current_files = {}
        for root, _, files in os.walk(project_path):
            if any(part.startswith('.') for part in Path(root).parts) or \
               any(part in ['venv', 'env', '__pycache__', 'node_modules'] for part in Path(root).parts):
                continue

            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    try:
                        mtime = os.path.getmtime(file_path)
                        current_files[file_path] = mtime
                    except OSError:
                        pass

        with state_lock:
            librarian_context["indexed_files"][project_path] = current_files
    except Exception as e:
        logger.error(f"Error updating librarian for {project_path}: {str(e)}")

# Create the monitoring thread but don't start it yet
monitoring_thread = threading.Thread(target=monitor_projects, daemon=True)
monitoring_started = False

def start_monitoring():
    """Start the monitoring thread after initialization is complete."""
    global monitoring_started
    if not monitoring_started:
        monitoring_thread.start()
        monitoring_started = True
        logger.info("Started monitoring thread after initialization")

# Register cleanup handler
def cleanup():
    global monitoring_active
    monitoring_active = False
    logger.info("Shutting down AI Librarian server")

    # Save any persistent state if needed
    try:
        # Use current_dir which is safely defined at the top of the file
        # Instead of relying on __file__ which might not be available in all contexts
        state_file = os.path.join(current_dir, "ai_librarian_state.json")
        
        with state_lock:
            state = {
                "active_projects": list(librarian_context["active_projects"]),
                "last_update": librarian_context["last_update"]
            }
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving state: {str(e)}")

atexit.register(cleanup)

# Add tool to get cache statistics
@mcp.tool()
def get_file_cache_stats() -> Dict[str, Any]:
    """
    Get statistics about the file cache.
    
    Returns:
        Dictionary with cache statistics including hit rate
    """
    with state_lock:
        entries = len(librarian_context["file_cache"])
        hits = librarian_context["cache_stats"]["hits"]
        misses = librarian_context["cache_stats"]["misses"]
        total = hits + misses
        hit_ratio = hits / total if total > 0 else 0
        
        return {
            "status": "success",
            "cache_entries": entries,
            "cache_size_limit": librarian_context["cache_max_size"],
            "cache_age_limit": librarian_context["cache_max_age"],
            "hits": hits,
            "misses": misses,
            "hit_ratio": hit_ratio,
            "cached_files": list(librarian_context["file_cache"].keys())
        }

@mcp.tool()
def clear_file_cache_tool() -> Dict[str, Any]:
    """
    Clear the file cache and return statistics.
    
    This is useful to free up memory or if you want to force fresh reads.
    
    Returns:
        Dictionary with cache statistics
    """
    stats = clear_file_cache()
    return {
        "status": "success",
        "entries_cleared": stats["entries_cleared"],
        "hits": stats["hits"],
        "misses": stats["misses"],
        "hit_ratio": stats["hit_ratio"],
        "message": f"Cache cleared. {stats['entries_cleared']} entries removed."
    }

# Load previous state if available
state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_librarian_state.json")
if os.path.exists(state_file):
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
            with state_lock:
                librarian_context["active_projects"] = set(state.get("active_projects", []))
                librarian_context["last_update"] = state.get("last_update", {})

        # Reload active projects
        for project_path in list(librarian_context["active_projects"]):
            if os.path.exists(project_path):
                logger.info(f"Reloading project: {project_path}")
                update_librarian_for_project(project_path)
            else:
                logger.warning(f"Previously active project not found: {project_path}")
                with state_lock:
                    librarian_context["active_projects"].remove(project_path)
    except Exception as e:
        logger.error(f"Error loading state: {str(e)}")

# Dictionary to store permission status of directories
permission_status = {}

# File cache management functions
def cache_get_file(file_path: str, encoding: str = "utf-8") -> Optional[Dict[str, Any]]:
    """
    Get a file from the cache if available and not expired.
    
    Args:
        file_path: Path to the file
        encoding: File encoding
        
    Returns:
        Cached file data or None if not available
    """
    with state_lock:
        # Check if file is in cache
        if file_path not in librarian_context["file_cache"]:
            librarian_context["cache_stats"]["misses"] += 1
            return None
            
        # Get cached entry
        cache_entry = librarian_context["file_cache"][file_path]
        
        # Check if cache entry is expired
        current_time = time.time()
        if current_time - cache_entry["cached_at"] > librarian_context["cache_max_age"]:
            # Entry is expired, remove it
            del librarian_context["file_cache"][file_path]
            librarian_context["cache_stats"]["misses"] += 1
            return None
            
        # Check if the file has been modified since it was cached
        try:
            stats = os.stat(file_path)
            if stats.st_mtime > cache_entry["modified"]:
                # File has been modified, remove from cache
                del librarian_context["file_cache"][file_path]
                librarian_context["cache_stats"]["misses"] += 1
                return None
        except Exception:
            # If there's an error checking the file, assume it's invalid
            del librarian_context["file_cache"][file_path]
            librarian_context["cache_stats"]["misses"] += 1
            return None
            
        # Cache hit
        librarian_context["cache_stats"]["hits"] += 1
        # Update access time
        cache_entry["last_accessed"] = current_time
        
        return cache_entry

def cache_set_file(file_path: str, file_data: Dict[str, Any]) -> None:
    """
    Add or update a file in the cache.
    
    Args:
        file_path: Path to the file
        file_data: File data dictionary
    """
    with state_lock:
        # Check if cache is full
        if len(librarian_context["file_cache"]) >= librarian_context["cache_max_size"]:
            # Remove the least recently accessed entry
            lru_path = min(
                librarian_context["file_cache"].items(),
                key=lambda x: x[1]["last_accessed"]
            )[0]
            del librarian_context["file_cache"][lru_path]
            
        # Add the file to the cache
        current_time = time.time()
        librarian_context["file_cache"][file_path] = {
            **file_data,
            "cached_at": current_time,
            "last_accessed": current_time
        }

def clear_file_cache() -> Dict[str, Any]:
    """
    Clear the file cache and return statistics.
    
    Returns:
        Dictionary with cache statistics
    """
    with state_lock:
        stats = {
            "entries_cleared": len(librarian_context["file_cache"]),
            "hits": librarian_context["cache_stats"]["hits"],
            "misses": librarian_context["cache_stats"]["misses"],
            "hit_ratio": 0
        }
        
        # Calculate hit ratio
        total_accesses = stats["hits"] + stats["misses"]
        if total_accesses > 0:
            stats["hit_ratio"] = stats["hits"] / total_accesses
            
        # Reset cache
        librarian_context["file_cache"] = {}
        librarian_context["cache_stats"] = {"hits": 0, "misses": 0}
        
        return stats

# Parse directories from command line args
def initialize_allowed_directories():
    allowed_dirs = []

    # Check for directories in command line args
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if os.path.exists(arg):
                allowed_dirs.append(os.path.abspath(arg))
                logger.info(f"Added allowed directory from command line: {arg}")

    # Add the current directory as a fallback
    if not allowed_dirs:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(script_dir)
        allowed_dirs.append(parent_dir)
        logger.info(f"Added parent directory: {parent_dir}")

    # Update our permission status tracker
    for dir_path in allowed_dirs:
        permission_status[dir_path] = True

    return allowed_dirs

# Get allowed directories
ALLOWED_DIRECTORIES = initialize_allowed_directories()

# Initialize Tool Index integration
def initialize_tool_index():
    """
    Check for Tool Index in allowed directories and initialize integration.
    
    Returns:
        Path to the Tool Index directory if found, None otherwise
    """
    tool_index_path = None

    for project_path in ALLOWED_DIRECTORIES:
        potential_path = os.path.join(project_path, ".tool_reference")
        if os.path.exists(potential_path):
            tool_index_path = potential_path
            logger.info(f"Found Tool Index at {tool_index_path}")
            break

    # Store the path in the global context
    with state_lock:
        librarian_context["tool_index"] = tool_index_path

    return tool_index_path

# Initialize Tool Index
TOOL_INDEX_PATH = initialize_tool_index()

# Initialize Unified Context Integration
if register_unified_context_tools is not None:
    register_unified_context_tools(mcp)
    logger.info("Registered Unified Context tools")

def query_tool_index(query_type, query_params):
    """
    Query the Tool Index for information.
    
    Args:
        query_type: Type of query (profile, relationship, decision_tree)
        query_params: Parameters for the query
        
    Returns:
        Query results or None if not found
    """
    tool_index_path = librarian_context["tool_index"]

    # First verification step - verify Tool Index exists
    if not tool_index_path:
        logger.warning(f"Tool Index not found when querying {query_type}")
        return None

    # Second verification step - verify required directories exist
    required_directories = {
        "tool_profiles": os.path.join(tool_index_path, "tool_profiles"),
        "decision_trees": os.path.join(tool_index_path, "decision_trees")
    }

    for dir_name, dir_path in required_directories.items():
        if not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path, exist_ok=True)
                logger.info(f"Created missing directory: {dir_path}")
            except Exception as e:
                logger.error(f"Failed to create missing directory {dir_path}: {str(e)}")
                return None

    # Third verification step - verify registry.json exists
    registry_path = os.path.join(tool_index_path, "registry.json")
    if not os.path.exists(registry_path):
        logger.error(f"Registry file not found: {registry_path}")
        return {
            "error": "Tool Index registry.json not found",
            "message": "The Tool Index requires a registry.json file to function properly."
        }

    try:
        if query_type == "profile":
            tool_name = query_params.get("tool")
            if not tool_name:
                logger.warning("No tool name provided for profile query")
                return None

            profile_path = os.path.join(tool_index_path, "tool_profiles", f"{tool_name}.json")

            # Fallback for missing profiles
            if not os.path.exists(profile_path):
                logger.info(f"Profile not found for tool: {tool_name}, using default profile")
                # Return a basic profile with essential information
                return {
                    "tool_id": tool_name,
                    "primary_purpose": f"Function {tool_name} - refer to its documentation",
                    "parameter_patterns": {},
                    "always_use_when": [],
                    "never_use_when": [],
                    "_fallback_profile": True
                }

            with open(profile_path, 'r', encoding='utf-8') as f:
                return json.load(f)

        elif query_type == "relationship":
            rel_group = query_params.get("group")
            if not rel_group:
                logger.warning("No relationship group provided for query")
                return None

            # First check for a dedicated relationship file
            rel_path = os.path.join(tool_index_path, f"relationship_{rel_group}.json")
            if os.path.exists(rel_path):
                with open(rel_path, 'r', encoding='utf-8') as f:
                    return json.load(f)

            # Then check in the registry file
            with open(registry_path, 'r', encoding='utf-8') as f:
                registry = json.load(f)
                if "relationships" in registry:
                    for rel in registry["relationships"]:
                        if rel.get("group_name") == rel_group:
                            return rel

            # Fallback for missing relationships
            logger.info(f"Relationship group not found: {rel_group}")
            return {
                "group_name": rel_group,
                "description": f"Relationship group for {rel_group}",
                "tools": [],
                "common_sequences": [],
                "_fallback_relationship": True
            }

        elif query_type == "decision_tree":
            tree_id = query_params.get("tree_id")
            if not tree_id:
                logger.warning("No tree_id provided for decision tree query")
                return None

            tree_path = os.path.join(tool_index_path, "decision_trees", f"{tree_id}.json")
            if os.path.exists(tree_path):
                with open(tree_path, 'r', encoding='utf-8') as f:
                    return json.load(f)

            # Fallback for missing decision trees
            logger.info(f"Decision tree not found: {tree_id}")
            return {
                "tree_id": tree_id,
                "description": f"Decision tree for {tree_id}",
                "decision_nodes": [],
                "_fallback_tree": True
            }

        elif query_type == "registry":
            with open(registry_path, 'r', encoding='utf-8') as f:
                return json.load(f)

        elif query_type == "categories":
            categories_path = os.path.join(tool_index_path, "categories.json")
            if not os.path.exists(categories_path):
                logger.info("Categories file not found, extracting from registry")
                # Create a basic categories structure from registry
                with open(registry_path, 'r', encoding='utf-8') as f:
                    registry = json.load(f)

                # Extract relationships as categories
                categories = {
                    "version": registry.get("version", "1.0.0"),
                    "categories": []
                }

                if "relationships" in registry:
                    for rel in registry["relationships"]:
                        if "group_name" in rel and "tools" in rel:
                            categories["categories"].append({
                                "name": rel["group_name"],
                                "description": rel.get("description", f"Tools related to {rel['group_name']}"),
                                "tools": rel["tools"]
                            })

                return categories

            with open(categories_path, 'r', encoding='utf-8') as f:
                return json.load(f)

    except Exception as e:
        logger.error(f"Error querying Tool Index: {str(e)}")
        return {
            "error": f"Error querying Tool Index: {str(e)}",
            "query_type": query_type,
            "query_params": query_params
        }

    return None

def query_tool_index_for_taskboard(task_type):
    """
    Query the Tool Index for TaskBoard-specific information.
    
    Args:
        task_type: Type of task being processed
        
    Returns:
        Information about which mini-librarians to use for the task
    """
    tool_index_path = librarian_context["tool_index"]

    # Verification step - verify Tool Index exists
    if not tool_index_path:
        logger.warning(f"Tool Index not found when querying for TaskBoard task type: {task_type}")
        return None

    # Default mappings to ensure resilient behavior even without registry
    default_mappings = {
        "component_analysis": ["component-analyzer"],
        "find_usages": ["file-indexer", "component-analyzer"],
        "code_modification": ["file-indexer", "component-analyzer", "code-modifier"],
        "file_search": ["file-indexer"],
        "todo_management": ["todo-manager"]
    }

    try:
        # Check for TaskBoard integration information
        registry_path = os.path.join(tool_index_path, "registry.json")

        # Verify registry exists
        if not os.path.exists(registry_path):
            logger.warning(f"Registry file not found: {registry_path}, using default mappings")
            if task_type in default_mappings:
                return {
                    "mini_librarians": default_mappings[task_type],
                    "task_type": task_type,
                    "_using_default": True
                }
            return None

        # Read and process registry
        with open(registry_path, 'r', encoding='utf-8') as f:
            registry = json.load(f)

        # Check for TaskBoard integration section
        if "taskboard_integration" in registry:
            mapping = registry["taskboard_integration"].get("task_type_to_mini_librarian_mapping", {})

            # If task type is found in mapping, return it
            if task_type in mapping:
                return {
                    "mini_librarians": mapping[task_type],
                    "task_type": task_type
                }

            # If task type not found but we have other mappings, try to find related tasks
            logger.info(f"Task type '{task_type}' not found in mappings, attempting to find similar")

            # Try to find similar task types by partial matching
            similar_tasks = []
            for known_type in mapping.keys():
                if known_type in task_type or task_type in known_type:
                    similar_tasks.append(known_type)

            if similar_tasks:
                # Use the first similar task found
                similar_task = similar_tasks[0]
                logger.info(f"Using similar task type: {similar_task} for {task_type}")
                return {
                    "mini_librarians": mapping[similar_task],
                    "task_type": task_type,
                    "mapped_from": similar_task,
                    "_similar_match": True
                }

        # Fall back to default mappings if no specific mapping found
        if task_type in default_mappings:
            logger.info(f"Using default mapping for task type: {task_type}")
            return {
                "mini_librarians": default_mappings[task_type],
                "task_type": task_type,
                "_using_default": True
            }

    except Exception as e:
        logger.error(f"Error querying Tool Index for TaskBoard: {str(e)}")

        # Even on error, try to provide default mappings
        if task_type in default_mappings:
            logger.info(f"Using default mapping for task type {task_type} after error")
            return {
                "mini_librarians": default_mappings[task_type],
                "task_type": task_type,
                "_using_default": True,
                "_error_recovery": True
            }

    return None

def determine_mini_librarians(task_type, task_params=None):
    """
    Determine which mini-librarians should handle a TaskBoard task.
    
    This function implements a resilient approach to determine which mini-librarians
    should handle a particular task type, with multiple fallback strategies.
    
    Args:
        task_type: Type of task
        task_params: Task parameters (optional)
        
    Returns:
        List of mini-librarian IDs that should handle the task
    """
    logger.debug(f"Determining mini-librarians for task type: {task_type}")

    # First verification step - ensure we have a valid task type
    if not task_type:
        logger.warning("No task type provided to determine_mini_librarians")
        return ["general-assistant"]  # Default to general assistant for unspecified tasks

    # Default mappings for known task types (hardcoded fallback)
    default_mappings = {
        "component_analysis": ["component-analyzer"],
        "find_usages": ["file-indexer", "component-analyzer"],
        "code_modification": ["file-indexer", "component-analyzer", "code-modifier"],
        "file_search": ["file-indexer"],
        "todo_management": ["todo-manager"],
        "diagnostics": ["diagnostics-runner"]
    }

    # Special case for task parameters with specific requirements
    if task_params:
        # Check if task parameters indicate specific mini-librarians
        if task_params.get("mini_librarians"):
            logger.info(f"Using explicitly specified mini-librarians from task parameters")
            return task_params.get("mini_librarians")

        # Check if task involves file operations
        if "file" in task_params or "path" in task_params:
            if "file-indexer" not in default_mappings.get(task_type, []):
                logger.info("Task involves file operations, adding file-indexer")
                # Ensure file operations get the file indexer involved
                if task_type in default_mappings:
                    # Add file-indexer if not already present
                    librarians = default_mappings[task_type].copy()
                    if "file-indexer" not in librarians:
                        librarians.append("file-indexer")
                    return librarians

    # First query the Tool Index for best information
    tool_index_info = query_tool_index_for_taskboard(task_type)

    if tool_index_info and "mini_librarians" in tool_index_info:
        logger.info(f"Using mini-librarians from Tool Index: {tool_index_info['mini_librarians']}")
        return tool_index_info["mini_librarians"]

    # Fallback to hardcoded defaults if Tool Index query failed
    if task_type in default_mappings:
        logger.info(f"Using default mini-librarians for task type: {task_type}")
        return default_mappings[task_type]

    # Try to infer based on task type name
    for known_type, librarians in default_mappings.items():
        if known_type in task_type or task_type in known_type:
            logger.info(f"Inferring mini-librarians based on similar task type: {known_type}")
            return librarians

    # Ultimate fallback - use general assistant
    logger.info(f"No matching mini-librarians found for task type: {task_type}, using general-assistant")
    return ["general-assistant"]

# Function to validate paths (used in edit_file and other functions)
def validate_path(path, allowed_directories):
    """
    Validate that a path is within allowed directories.
    
    Args:
        path: Path to validate
        allowed_directories: List of allowed directories
        
    Returns:
        True if path is valid, False otherwise
    """
    # Normalize path
    path = os.path.abspath(path)

    # Check if path is within allowed directories
    return any(path.startswith(allowed_dir) for allowed_dir in allowed_directories)

# Utility function to pause/resume monitoring during operations
def pause_monitoring():
    with state_lock:
        librarian_context["paused"] = True
        logger.debug("Monitoring paused")

def resume_monitoring():
    with state_lock:
        librarian_context["paused"] = False
        logger.debug("Monitoring resumed")

# Context manager for pausing monitoring
class MonitoringPauser:
    def __enter__(self):
        pause_monitoring()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        resume_monitoring()

@mcp.tool()
def list_allowed_directories() -> List[str]:
    """
    Returns the list of directories that this server is allowed to access.
    
    Returns:
        A list of allowed directory paths
    """
    return ALLOWED_DIRECTORIES

@mcp.tool()
def check_project_access(project_path: str) -> str:
    """
    Check if the server has permission to access a specific project directory.
    This is required before initializing the AI Librarian for a project.
    
    Args:
        project_path: The project directory to check
        
    Returns:
        Status message about directory access
    """
    try:
        # Normalize the path
        project_path = os.path.abspath(project_path)

        # First check our permission tracker
        if project_path in permission_status and permission_status[project_path]:
            return f"✅ The server has permission to access: {project_path}\n\nYou can initialize the AI Librarian for this project."

        # Check if the path is within any of the allowed directories
        for allowed_dir in ALLOWED_DIRECTORIES:
            if project_path.startswith(allowed_dir) or allowed_dir.startswith(project_path):
                permission_status[project_path] = True
                return f"✅ The server has permission to access: {project_path}\n\nYou can initialize the AI Librarian for this project."

        # Try to access the directory
        if not os.path.exists(project_path):
            return f"❌ Directory does not exist: {project_path}"

        # Try to list the directory contents as a basic access test
        try:
            os.listdir(project_path)
            # If we get here, we have access
            permission_status[project_path] = True
            return f"✅ The server has permission to access: {project_path}\n\nYou can initialize the AI Librarian for this project."
        except PermissionError:
            permission_status[project_path] = False
            return f"❌ Permission denied: {project_path}\n\nPlease grant access to this directory in Claude Desktop:\n" + \
                   "1. Open Claude Desktop settings\n" + \
                   "2. Go to MCP Servers\n" + \
                   "3. Find 'AI Librarian'\n" + \
                   "4. Click 'Edit Permissions'\n" + \
                   f"5. Grant access to {project_path}"
    except Exception as e:
        logger.error(f"Error checking project access: {str(e)}")
        return f"❌ Error checking access: {str(e)}"

#-----------------------------------------------------------------
# AI Librarian Core Implementation
#-----------------------------------------------------------------

def scan_directory(directory: str, exclude_dirs: Optional[List[str]] = None) -> List[str]:
    """
    Scan a directory for Python files.
    
    Args:
        directory: The directory to scan
        exclude_dirs: Optional list of directories to exclude
        
    Returns:
        List of paths to Python files
    """
    if exclude_dirs is None:
        exclude_dirs = ['venv', 'env', '.venv', '.env', '__pycache__', 'node_modules', '.git']

    python_files = []

    for root, dirs, files in os.walk(directory):
        # Skip excluded directories
        dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith('.')]

        for file in files:
            if file.endswith('.py'):
                python_files.append(os.path.join(root, file))

    return python_files

def parse_python_file(file_path: str) -> Dict[str, List[str]]:
    """
    Parse a Python file and extract its structure.
    
    Args:
        file_path: Path to the Python file
        
    Returns:
        Dictionary containing classes and functions in the file
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        tree = ast.parse(content)

        classes = []
        functions = []
        imports = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(node.name)
            elif isinstance(node, ast.FunctionDef):
                functions.append(node.name)
            elif isinstance(node, ast.Import):
                for name in node.names:
                    imports.append(name.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for name in node.names:
                    imports.append(f"{module}.{name.name}")

        return {
            "classes": classes,
            "functions": functions,
            "imports": imports
        }
    except Exception as e:
        logger.error(f"Error parsing {file_path}: {e}")
        return {
            "classes": [],
            "functions": [],
            "imports": []
        }

def generate_mini_librarian(file_path: str, file_info: Dict[str, List[str]], output_dir: str) -> str:
    """
    Generate a mini-librarian JSON file for a Python file.
    
    Args:
        file_path: Path to the Python file
        file_info: Dictionary containing file information (classes, functions)
        output_dir: Directory where the mini-librarian should be saved
        
    Returns:
        Path to the generated mini-librarian file
    """
    # Create a relative path for the mini-librarian
    rel_path = os.path.relpath(file_path, os.path.dirname(output_dir))
    rel_path = rel_path.replace('\\', '/')

    # Create output path
    mini_librarian_path = os.path.join(
        output_dir,
        f"{rel_path.replace('/', '_').replace('.', '_')}.json"
    )

    # Add file description
    description = f"Mini-librarian for {rel_path}"

    # Create the mini-librarian content
    mini_librarian = {
        "file_path": rel_path,
        "classes": file_info["classes"],
        "functions": file_info["functions"],
        "imports": file_info["imports"],
        "description": description
    }

    # Write the mini-librarian
    os.makedirs(os.path.dirname(mini_librarian_path), exist_ok=True)
    with open(mini_librarian_path, 'w', encoding='utf-8') as f:
        json.dump(mini_librarian, f, indent=2)

    return os.path.relpath(mini_librarian_path, output_dir)

def generate_script_index(files_info: Dict[str, Dict], output_file: str) -> None:
    """
    Generate the script index file.
    
    Args:
        files_info: Dictionary containing information about all files
        output_file: Path where the script index should be saved
    """
    script_index = {"files": {}, "version": "0.1.0"}

    for file_path, info in files_info.items():
        rel_path = file_path.replace('\\', '/')
        script_index["files"][rel_path] = {
            "path": rel_path,
            "classes": info["file_info"]["classes"],
            "functions": info["file_info"]["functions"],
            "mini_librarian": info["mini_librarian_path"]
        }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(script_index, f, indent=2)

def generate_component_registry(files_info: Dict[str, Dict], output_file: str) -> None:
    """
    Generate the component registry file.
    
    Args:
        files_info: Dictionary containing information about all files
        output_file: Path where the component registry should be saved
    """
    components = {}

    # Collect all components
    for file_path, info in files_info.items():
        file_info = info["file_info"]
        rel_path = file_path.replace('\\', '/')

        # Add classes
        for class_name in file_info["classes"]:
            components[class_name] = {
                "type": "class",
                "file": rel_path,
                "references": []
            }

        # Add functions
        for func_name in file_info["functions"]:
            components[func_name] = {
                "type": "function",
                "file": rel_path,
                "references": []
            }

    # Write the component registry
    registry = {
        "components": components,
        "version": "0.1.0"
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(registry, f, indent=2)

@mcp.tool()
def initialize_librarian(project_path: str) -> str:
    """
    Initialize the AI Librarian for a project.
    
    This tool creates the .ai_reference directory structure and builds a persistent
    context that Claude can access across conversations. After initialization, the
    project will be actively monitored for changes, automatically updating the context.
    
    Args:
        project_path: The root directory of the project
        
    Returns:
        A success message or error information
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Check permission first
            project_path = os.path.abspath(project_path)
            if project_path not in permission_status or not permission_status[project_path]:
                # Try to check access
                try:
                    if not os.path.exists(project_path):
                        return f"❌ Directory does not exist: {project_path}"

                    # Try to list the directory contents as a basic access test
                    os.listdir(project_path)
                    # If we get here, we have access
                    permission_status[project_path] = True
                except PermissionError:
                    return f"❌ Permission denied: {project_path}\n\nPlease grant access to this directory in Claude Desktop first:\n" + \
                           f"1. Use check_project_access(\"{project_path}\") to verify access\n" + \
                           "2. If needed, edit Claude Desktop permissions settings"

            # Create the .ai_reference directory
            ai_ref_path = os.path.join(project_path, ".ai_reference")
            os.makedirs(ai_ref_path, exist_ok=True)

            # Create subdirectories
            scripts_path = os.path.join(ai_ref_path, "scripts")
            diagnostics_path = os.path.join(ai_ref_path, "diagnostics")
            edit_bookmarks_path = os.path.join(ai_ref_path, "edit_bookmarks")
            os.makedirs(scripts_path, exist_ok=True)
            os.makedirs(diagnostics_path, exist_ok=True)
            os.makedirs(edit_bookmarks_path, exist_ok=True)

            # Create README.md
            readme_content = """# AI Librarian

This directory contains the AI Librarian reference system for this project.
It helps AI assistants understand and navigate the codebase.

## Structure

- `component_registry.json` - Registry of all code components
- `script_index.json` - Index of all script files
- `scripts/` - Mini-librarians for individual scripts
- `diagnostics/` - Diagnostic information and troubleshooting

## Usage

The AI Librarian is automatically maintained by the AI Librarian MCP server.
Changes to your codebase will be tracked in real-time, maintaining context across conversations.
"""
            with open(os.path.join(ai_ref_path, "README.md"), 'w', encoding='utf-8') as f:
                f.write(readme_content)

            # Create component_registry.json
            component_registry = {"components": {}, "version": "0.1.0"}
            with open(os.path.join(ai_ref_path, "component_registry.json"), 'w', encoding='utf-8') as f:
                json.dump(component_registry, f, indent=2)

            # Create script_index.json
            script_index = {"files": {}, "version": "0.1.0"}
            with open(os.path.join(ai_ref_path, "script_index.json"), 'w', encoding='utf-8') as f:
                json.dump(script_index, f, indent=2)

            # Create a diagnostic README
            diag_readme = """# Diagnostics

This directory contains diagnostic information for the AI Librarian.
Diagnostic files help troubleshoot issues with code understanding and navigation.
"""
            with open(os.path.join(diagnostics_path, "README.md"), 'w', encoding='utf-8') as f:
                f.write(diag_readme)

            # Add project to active monitoring list
            with state_lock:
                librarian_context["active_projects"].add(project_path)
                librarian_context["last_update"][project_path] = time.time()

            # Run initial generation - using the imported initialize_enhanced_librarian
            update_librarian_for_project(project_path)

            logger.info(f"Added project to active monitoring: {project_path}")

            # Run diagnostic checks to verify librarian functionality
            diagnostic_results = run_librarian_diagnostics(project_path)

            return f"Successfully initialized AI Librarian at {ai_ref_path}\n\n" + \
                   "Project is now being actively monitored for changes. Any updates to the codebase " + \
                   "will be automatically detected and processed. Claude will maintain context awareness " + \
                   "across conversations, allowing for more effective assistance with this project.\n\n" + \
                   diagnostic_results
        except Exception as e:
            logger.error(f"Error initializing AI Librarian: {str(e)}")
            return f"Error initializing AI Librarian: {str(e)}"

@mcp.tool()
def query_component(project_path: str, component_name: str, use_cache: bool = True) -> Dict[str, Any]:
    """
    Query information about a specific component in the project.
    
    This tool searches for a component (class or function) in the project and returns
    detailed information about it. It first checks the AI Librarian index for faster lookup,
    and uses file caching to improve performance.
    
    Args:
        project_path: The root directory of the project
        component_name: The name of the component to query
        use_cache: Whether to use the file cache (default: True)
        
    Returns:
        Detailed information about the component
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Check if project is in our active monitoring
            with state_lock:
                is_active = project_path in librarian_context["active_projects"]

            if is_active:
                logger.info(f"Using in-memory context for querying component: {component_name}")
            else:
                logger.info(f"Project not in active monitoring, checking disk: {project_path}")

            # Check if the AI Librarian exists
            ai_ref_path = os.path.join(project_path, ".ai_reference")
            if not os.path.exists(ai_ref_path):
                return {
                    "status": "error",
                    "message": f"AI Librarian not initialized at {project_path}. Run initialize_librarian first."
                }

            # Get script index - first check in-memory, then fallback to file
            script_index = None
            
            # Check for component registry first (faster lookup)
            component_registry_path = os.path.join(ai_ref_path, "component_registry.json")
            if os.path.exists(component_registry_path):
                # Check cache first
                registry_cached = False
                if use_cache:
                    registry_data = cache_get_file(component_registry_path)
                    if registry_data and registry_data.get("content"):
                        try:
                            registry = json.loads(registry_data["content"])
                            registry_cached = True
                        except:
                            logger.warning("Failed to parse cached registry, reading from disk")
                
                # If not cached or cache disabled, read from disk
                if not registry_cached:
                    try:
                        with open(component_registry_path, 'r', encoding='utf-8') as f:
                            registry = json.load(f)
                            # Add to cache if enabled
                            if use_cache:
                                cache_set_file(component_registry_path, {
                                    "status": "success",
                                    "path": component_registry_path,
                                    "content": json.dumps(registry),
                                    "size": os.path.getsize(component_registry_path),
                                    "mime_type": "application/json",
                                    "encoding": "utf-8",
                                    "modified": os.path.getmtime(component_registry_path)
                                })
                    except Exception as e:
                        logger.warning(f"Error reading component registry: {str(e)}")
                        registry = None
                
                # If we found the component in registry, use that info directly
                if registry and "components" in registry and component_name in registry["components"]:
                    component_info = registry["components"][component_name]
                    logger.info(f"Component found directly in registry: {component_name}")
                    
                    # Get the file containing the component
                    file_path = component_info.get("file", "")
                    full_file_path = os.path.join(project_path, file_path)
                    
                    # Use our cached file reading for better performance
                    file_result = None
                    
                    if os.path.exists(full_file_path) and os.access(full_file_path, os.R_OK):
                        # Check cache first
                        if use_cache:
                            file_data = cache_get_file(full_file_path)
                            if file_data and file_data.get("status") == "success":
                                file_result = file_data
                                logger.info(f"Using cached file for component: {component_name}")
                        
                        # If not in cache, read from disk
                        if file_result is None:
                            try:
                                with open(full_file_path, 'r', encoding='utf-8') as f:
                                    file_content = f.read()
                                
                                # Create file result 
                                file_result = {
                                    "status": "success",
                                    "path": full_file_path,
                                    "content": file_content,
                                    "size": os.path.getsize(full_file_path),
                                    "mime_type": "text/x-python",
                                    "encoding": "utf-8",
                                    "modified": os.path.getmtime(full_file_path)
                                }
                                
                                # Add to cache if enabled
                                if use_cache:
                                    cache_set_file(full_file_path, file_result)
                            except Exception as e:
                                logger.error(f"Error reading file: {str(e)}")
                    
                    # Extract the component code if we have the file content
                    code_snippet = "Code not available"
                    if file_result and file_result.get("content"):
                        try:
                            # Extract the component's code
                            tree = ast.parse(file_result["content"])
                            for node in ast.walk(tree):
                                if ((isinstance(node, ast.ClassDef) or isinstance(node, ast.FunctionDef)) and
                                    node.name == component_name):
                                    
                                    # Get the component's source code
                                    start_line = node.lineno
                                    end_line = node.end_lineno if hasattr(node, 'end_lineno') else start_line + 1
                                    
                                    # Extract line numbers and code
                                    lines = file_result["content"].splitlines()
                                    code_snippet = "\n".join(lines[start_line-1:end_line])
                                    break
                        except Exception as e:
                            logger.error(f"Error parsing file for component code: {str(e)}")
                    
                    # Return the component information with highlighted source
                    return {
                        "status": "success",
                        "component": component_name,
                        "type": component_info.get("type", "unknown"),
                        "file": file_path,
                        "full_path": full_file_path,
                        "code": code_snippet,
                        "references": component_info.get("references", []),
                        "description": component_info.get("description", "No description available"),
                        "using_registry": True,
                        "from_cache": file_result and file_result.get("from_cache", False)
                    }
            
            # Fall back to script index if registry approach failed
            with state_lock:
                if project_path in librarian_context["projects"]:
                    script_index = librarian_context["projects"][project_path]
                    logger.info("Using in-memory script index")

            if script_index is None:
                script_index_path = os.path.join(ai_ref_path, "script_index.json")
                if not os.path.exists(script_index_path):
                    return {
                        "status": "error",
                        "message": f"Script index not found at {script_index_path}."
                    }

                # Try to use cache for script index
                script_index_cached = False
                if use_cache:
                    index_data = cache_get_file(script_index_path)
                    if index_data and index_data.get("content"):
                        try:
                            script_index = json.loads(index_data["content"])
                            script_index_cached = True
                            logger.info("Using cached script index")
                        except:
                            logger.warning("Failed to parse cached index, reading from disk")
                
                # If not cached or parsing failed, read from disk
                if not script_index_cached:
                    with open(script_index_path, 'r', encoding='utf-8') as f:
                        script_index = json.load(f)
                        # Cache it for future use
                        with state_lock:
                            librarian_context["projects"][project_path] = script_index
                        
                        # Add to file cache if enabled
                        if use_cache:
                            cache_set_file(script_index_path, {
                                "status": "success",
                                "path": script_index_path,
                                "content": json.dumps(script_index),
                                "size": os.path.getsize(script_index_path),
                                "mime_type": "application/json",
                                "encoding": "utf-8",
                                "modified": os.path.getmtime(script_index_path)
                            })

            # Search for the component in all files
            results = []

            for file_path, file_info in script_index["files"].items():
                if (component_name in file_info.get("classes", []) or
                    component_name in file_info.get("functions", [])):

                    # Read the mini-librarian for more details
                    mini_librarian_path = os.path.join(ai_ref_path, file_info["mini_librarian"])
                    
                    # Check cache for mini-librarian
                    mini_librarian = None
                    if use_cache and os.path.exists(mini_librarian_path):
                        mini_lib_data = cache_get_file(mini_librarian_path)
                        if mini_lib_data and mini_lib_data.get("content"):
                            try:
                                mini_librarian = json.loads(mini_lib_data["content"])
                                logger.info(f"Using cached mini-librarian for {file_path}")
                            except:
                                logger.warning(f"Failed to parse cached mini-librarian, reading from disk: {mini_librarian_path}")
                    
                    # If not cached or parsing failed, read from disk
                    if mini_librarian is None and os.path.exists(mini_librarian_path):
                        try:
                            with open(mini_librarian_path, 'r', encoding='utf-8') as f:
                                mini_librarian = json.load(f)
                                
                                # Add to cache if enabled
                                if use_cache:
                                    cache_set_file(mini_librarian_path, {
                                        "status": "success",
                                        "path": mini_librarian_path,
                                        "content": json.dumps(mini_librarian),
                                        "size": os.path.getsize(mini_librarian_path),
                                        "mime_type": "application/json",
                                        "encoding": "utf-8",
                                        "modified": os.path.getmtime(mini_librarian_path)
                                    })
                        except Exception as e:
                            logger.warning(f"Error reading mini-librarian {mini_librarian_path}: {str(e)}")
                            mini_librarian = None

                    # Check if the file exists
                    full_file_path = os.path.join(project_path, file_path)
                    if os.path.exists(full_file_path):
                        # Use our cached read_file implementation for better performance
                        file_result = None
                        
                        # Check cache first
                        if use_cache:
                            file_data = cache_get_file(full_file_path)
                            if file_data and file_data.get("status") == "success":
                                file_result = file_data
                                logger.info(f"Using cached file for component: {component_name}")
                        
                        # If not in cache, read from disk
                        if file_result is None:
                            try:
                                with open(full_file_path, 'r', encoding='utf-8') as f:
                                    file_content = f.read()
                                
                                # Extract the component's code
                                import ast
                                try:
                                    tree = ast.parse(file_content)
                                    for node in ast.walk(tree):
                                        if ((isinstance(node, ast.ClassDef) or isinstance(node, ast.FunctionDef)) and
                                            node.name == component_name):

                                            # Get the component's source code
                                            start_line = node.lineno
                                            end_line = node.end_lineno if hasattr(node, 'end_lineno') else start_line + 1

                                            # Extract line numbers and code
                                            lines = file_content.splitlines()
                                            component_code = "\n".join(lines[start_line-1:end_line])

                                            # Add to results
                                            results.append({
                                                "file_path": file_path,
                                                "component_type": "class" if isinstance(node, ast.ClassDef) else "function",
                                                "line_range": f"{start_line}-{end_line}",
                                                "code": component_code
                                            })
                                            
                                            # Create file result and add to cache
                                            file_result = {
                                                "status": "success",
                                                "path": full_file_path,
                                                "content": file_content,
                                                "size": os.path.getsize(full_file_path),
                                                "mime_type": "text/x-python",
                                                "encoding": "utf-8",
                                                "modified": os.path.getmtime(full_file_path)
                                            }
                                            
                                            # Add to cache if enabled
                                            if use_cache:
                                                cache_set_file(full_file_path, file_result)
                                except Exception as e:
                                    logger.error(f"Error parsing file {full_file_path}: {str(e)}")
                                    results.append({
                                        "file_path": file_path,
                                        "error": f"Error parsing file: {str(e)}"
                                    })
                            except Exception as e:
                                logger.error(f"Error reading file {full_file_path}: {str(e)}")
                                results.append({
                                    "file_path": file_path,
                                    "error": f"Error reading file: {str(e)}"
                                })

            if not results:
                return {
                    "status": "error",
                    "message": f"Component '{component_name}' not found in the project."
                }

            # Return structured results
            return {
                "status": "success",
                "component_name": component_name,
                "found": True,
                "results": results,
                "count": len(results)
            }
        except Exception as e:
            logger.error(f"Error querying component: {str(e)}")
            return {
                "status": "error",
                "message": f"Error querying component: {str(e)}"
            }

@mcp.tool()
def find_implementation(project_path: str, search_text: str, file_pattern: str = None) -> Dict[str, Any]:
    """
    Find implementations containing the specified search text.
    
    Args:
        project_path: The root directory of the project
        search_text: The text to search for
        file_pattern: Optional pattern to filter files (e.g., "*.py")
        
    Returns:
        List of matching implementations with context
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Check if project is in active monitoring
            with state_lock:
                is_active = project_path in librarian_context["active_projects"]

            if is_active:
                logger.info(f"Using in-memory context for searching: {search_text}")

            results = []
            search_text = search_text.lower()

            # Determine which extensions to search based on file_pattern
            extensions = []
            if file_pattern:
                if "*." in file_pattern:
                    ext = file_pattern.split("*.")[-1]
                    extensions.append(f".{ext}")
                elif "." in file_pattern:
                    extensions.append(file_pattern)
            else:
                # Default to common code files
                extensions = [".py", ".js", ".ts", ".java", ".c", ".cpp", ".cs", ".go", ".rb", ".php"]

            # Function to check if a file should be searched
            def should_search_file(filename):
                if not extensions:
                    return True
                return any(filename.endswith(ext) for ext in extensions)

            # Walk the directory tree
            for root, dirs, files in os.walk(project_path):
                # Skip hidden directories and common excluded directories
                dirs[:] = [d for d in dirs if not d.startswith('.') and
                          d not in ['venv', 'env', 'node_modules', '__pycache__', '.git']]

                # Search files
                for filename in files:
                    if should_search_file(filename):
                        file_path = os.path.join(root, filename)
                        rel_path = os.path.relpath(file_path, project_path)

                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read()

                            # Search for the text
                            if search_text in content.lower():
                                # Find matching lines with context
                                lines = content.splitlines()
                                matches = []

                                for i, line in enumerate(lines):
                                    if search_text in line.lower():
                                        # Get context (3 lines before and after)
                                        start = max(0, i - 3)
                                        end = min(len(lines), i + 4)

                                        # Format the context
                                        context = []
                                        for j in range(start, end):
                                            line_num = j + 1
                                            line_text = lines[j]
                                            # Highlight the matching line
                                            if j == i:
                                                context.append(f"{line_num:4d}* {line_text}")
                                            else:
                                                context.append(f"{line_num:4d}  {line_text}")

                                        matches.append("\n".join(context))

                                if matches:
                                    results.append({
                                        "file": rel_path,
                                        "matches": matches
                                    })
                        except UnicodeDecodeError:
                            # Skip binary files
                            pass
                        except Exception as e:
                            logger.error(f"Error searching file {file_path}: {str(e)}")
                            # Don't include errors in results to avoid strange output

            # Return structured results
            if not results:
                return {
                    "status": "success",
                    "found": False,
                    "message": f"No matches found for '{search_text}'"
                }

            return {
                "status": "success",
                "found": True,
                "search_text": search_text,
                "file_pattern": file_pattern,
                "results": results,
                "count": len(results)
            }
        except Exception as e:
            logger.error(f"Error finding implementation: {str(e)}")
            return {
                "status": "error",
                "message": f"Error finding implementation: {str(e)}"
            }

@mcp.tool()
def initialize_tool_index(project_path: str) -> Dict[str, Any]:
    """
    Initialize the Tool Reference system for a project.
    
    This tool creates the .tool_reference directory structure and builds a comprehensive
    metadata system that helps Claude understand available tools and their relationships.
    Once initialized, Claude gains enhanced awareness of tool capabilities, relationships,
    and optimal usage patterns.
    
    Args:
        project_path: The root directory of the project
        
    Returns:
        Dictionary with the result of the operation
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            logger.info(f"Initializing Tool Reference system for {project_path}")
            
            # Validate project path
            if not os.path.exists(project_path):
                return {
                    "status": "error",
                    "message": f"Directory does not exist: {project_path}"
                }
            
            # Import the simple_tool_index module with absolute path
            from aitoolkit.librarian.simple_tool_index import initialize_tool_index as simple_initialize_tool_index
            
            # Initialize the tool reference using the simple implementation
            result = simple_initialize_tool_index(project_path)
            
            # Check if tool reference was successfully initialized
            if result.startswith("✅"):
                # Parse the statistics from the result
                tool_count = 0
                profile_count = 0
                relationship_count = 0
                decision_tree_count = 0
                
                # Extract statistics using regex
                import re
                tool_match = re.search(r'(\d+) tools', result)
                if tool_match:
                    tool_count = int(tool_match.group(1))
                
                profile_match = re.search(r'(\d+) detailed tool profiles', result)
                if profile_match:
                    profile_count = int(profile_match.group(1))
                
                relationship_match = re.search(r'(\d+) tool relationship', result)
                if relationship_match:
                    relationship_count = int(relationship_match.group(1))
                
                decision_match = re.search(r'(\d+) decision trees', result)
                if decision_match:
                    decision_tree_count = int(decision_match.group(1))
                
                # Check if needs cross-references with AI Librarian
                ai_ref_path = os.path.join(project_path, ".ai_reference")
                needs_cross_refs = os.path.exists(ai_ref_path)
                
                # Build cross-references if both AI Librarian and Tool Reference exist
                cross_refs_message = ""
                if needs_cross_refs:
                    try:
                        from .unified_context_integration import build_cross_references
                        cross_refs_result = build_cross_references(project_path)
                        if cross_refs_result.get("status") == "success":
                            cross_refs_count = len(cross_refs_result.get("cross_references", {}))
                            cross_refs_message = f"\n\n🔄 Built {cross_refs_count} cross-references between components and tools"
                    except Exception as e:
                        logger.warning(f"Error building cross-references: {str(e)}")
                        cross_refs_message = "\n\n⚠️ Cross-references could not be built automatically"
                
                return {
                    "status": "success",
                    "message": f"Tool Reference system initialized successfully for {project_path}",
                    "tool_count": tool_count,
                    "profile_count": profile_count,
                    "relationship_count": relationship_count,
                    "decision_tree_count": decision_tree_count,
                    "details": f"✅ Successfully initialized Tool Reference system\n\n" +
                              f"Tool Index Initialization Report:\n" +
                              f"✓ Tool registry created with {tool_count} tools\n" +
                              f"✓ {profile_count} detailed tool profiles generated\n" +
                              f"✓ {relationship_count} tool relationship groups defined\n" +
                              f"✓ {decision_tree_count} decision trees for tool selection" +
                              cross_refs_message +
                              f"\n\nClaude now has enhanced awareness of tool capabilities, " +
                              f"relationships between tools, and optimal usage patterns."
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to initialize Tool Reference: {result}"
                }
            
        except Exception as e:
            logger.error(f"Error initializing Tool Reference: {str(e)}")
            return {
                "status": "error",
                "message": f"Error initializing Tool Reference: {str(e)}"
            }

@mcp.tool()
def generate_librarian(project_path: str) -> str:
    """
    Generate or update the AI Librarian for a project.
    
    Args:
        project_path: The root directory of the project
        
    Returns:
        A success message with statistics or error information
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Check if the AI Librarian exists
            ai_ref_path = os.path.join(project_path, ".ai_reference")
            if not os.path.exists(ai_ref_path):
                return {
                    "status": "error",
                    "message": f"AI Librarian not initialized at {project_path}. Run initialize_librarian first."
                }

            # If project is not in active monitoring, add it
            with state_lock:
                if project_path not in librarian_context["active_projects"]:
                    librarian_context["active_projects"].add(project_path)
                    librarian_context["last_update"][project_path] = time.time()
                    logger.info(f"Added project to active monitoring: {project_path}")

            # Force update the librarian
            update_librarian_for_project(project_path)

            # Get stats
            file_count = 0
            component_count = 0

            # Count components from in-memory representation
            with state_lock:
                if project_path in librarian_context["components"]:
                    component_registry = librarian_context["components"][project_path]
                    component_count = len(component_registry.get("components", {}))

                # Count files from in-memory representation
                if project_path in librarian_context["indexed_files"]:
                    file_count = len(librarian_context["indexed_files"][project_path])

            # Run diagnostic checks to verify librarian functionality
            diagnostic_results = run_librarian_diagnostics(project_path)

            return f"Successfully generated AI Librarian for {project_path}:\n" + \
                   f"- {file_count} files indexed\n" + \
                   f"- {component_count} components identified\n\n" + \
                   "Project is now being actively monitored for changes. Claude will maintain " + \
                   "context awareness across conversations.\n\n" + \
                   diagnostic_results
        except Exception as e:
            logger.error(f"Error generating librarian: {str(e)}")
            return f"Error generating librarian: {str(e)}"

@mcp.tool()
def initialize_ai_dev_toolkit(project_path: str) -> Dict[str, Any]:
    """
    Initialize the complete AI Dev Toolkit for a project.
    
    This is a one-stop initialization tool that sets up both the AI Librarian 
    (for code understanding) and the Tool Reference System (for tool awareness) 
    in a single operation. After running this tool, Claude will have complete 
    context awareness of both code components and available tools.
    
    Args:
        project_path: The root directory of the project
        
    Returns:
        Dictionary containing initialization results
    """
    # Validate project path
    if not os.path.exists(project_path):
        return {
            "status": "error",
            "message": f"Directory does not exist: {project_path}"
        }
        
    # Step 1: Initialize AI Librarian
    logger.info(f"Initializing AI Dev Toolkit for {project_path}")
    librarian_result = initialize_librarian(project_path)
    
    # Check if librarian initialization was successful
    if isinstance(librarian_result, dict) and librarian_result.get("status") == "error":
        return {
            "status": "error",
            "message": f"Failed to initialize AI Librarian: {librarian_result.get('message', 'Unknown error')}"
        }
        
    # Step 2: Initialize Tool Reference using the simple implementation
    from aitoolkit.librarian.simple_tool_index import initialize_tool_index as simple_initialize_tool_index
    tool_result = simple_initialize_tool_index(project_path)
    
    # Parse tool initialization result
    tool_success = tool_result.startswith("✅")
    
    # Step 3: Create cross-references between systems
    cross_ref_result = None
    try:
        if tool_success:
            from aitoolkit.librarian.unified_context_integration import build_cross_references
            cross_ref_result = build_cross_references(project_path)
    except Exception as e:
        logger.error(f"Error building cross-references: {str(e)}")
        cross_ref_result = {
            "status": "error",
            "message": f"Error building cross-references: {str(e)}"
        }
    
    # Extract statistics for reporting
    # For AI Librarian
    file_count = 0
    component_count = 0
    with state_lock:
        if project_path in librarian_context["components"]:
            component_registry = librarian_context["components"][project_path]
            component_count = len(component_registry.get("components", {}))
        if project_path in librarian_context["indexed_files"]:
            file_count = len(librarian_context["indexed_files"][project_path])
    
    # For Tool Reference
    tool_count = 0
    profile_count = 0
    relationship_count = 0
    decision_tree_count = 0
    
    # Extract statistics using regex if tool initialization was successful
    if tool_success:
        import re
        tool_match = re.search(r'(\d+) tools', tool_result)
        if tool_match:
            tool_count = int(tool_match.group(1))
        
        profile_match = re.search(r'(\d+) detailed tool profiles', tool_result)
        if profile_match:
            profile_count = int(profile_match.group(1))
        
        relationship_match = re.search(r'(\d+) tool relationship', tool_result)
        if relationship_match:
            relationship_count = int(relationship_match.group(1))
        
        decision_match = re.search(r'(\d+) decision trees', tool_result)
        if decision_match:
            decision_tree_count = int(decision_match.group(1))
    
    # For Cross-References
    cross_ref_count = 0
    if cross_ref_result and isinstance(cross_ref_result, dict) and cross_ref_result.get("status") == "success":
        cross_ref_count = len(cross_ref_result.get("cross_references", {}))
    
    # Create detailed report
    report = f"""✅ AI Dev Toolkit Initialization Complete for {project_path}

┌─────────────────────────────────────────┐
│ AI Librarian Initialization:            │
├─────────────────────────────────────────┤
│ ✓ {file_count} files indexed            │
│ ✓ {component_count} components identified│
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ Tool Reference Initialization:          │
├─────────────────────────────────────────┤
│ ✓ {tool_count} tools registered         │
│ ✓ {profile_count} detailed tool profiles│
│ ✓ {relationship_count} relationship groups│
│ ✓ {decision_tree_count} decision trees  │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ Cross-References:                       │
├─────────────────────────────────────────┤
│ ✓ {cross_ref_count} bidirectional references│
└─────────────────────────────────────────┘

Claude now has complete context awareness of both code components and available tools.
This enables more intelligent assistance across all aspects of the project.
"""
    
    # Return results
    return {
        "status": "success",
        "message": "AI Dev Toolkit successfully initialized",
        "ai_librarian": {
            "file_count": file_count,
            "component_count": component_count
        },
        "tool_reference": {
            "tool_count": tool_count,
            "profile_count": profile_count,
            "relationship_count": relationship_count,
            "decision_tree_count": decision_tree_count
        },
        "cross_references": {
            "count": cross_ref_count
        },
        "details": report
    }                    

#-----------------------------------------------------------------
# Diagnostic Tools
#-----------------------------------------------------------------

def run_librarian_diagnostics(project_path: str) -> str:
    """
    Run diagnostic checks on the AI Librarian to verify proper functionality.
    
    Args:
        project_path: The root directory of the project
        
    Returns:
        A diagnostic report message
    """
    try:
        logger.info(f"Running diagnostic checks for AI Librarian in {project_path}")
        results = ["🔍 AI Librarian Diagnostic Report:"]

        # 1. Check AI Reference Directory
        ai_ref_path = os.path.join(project_path, ".ai_reference")
        if os.path.exists(ai_ref_path):
            results.append("✓ .ai_reference directory exists")
        else:
            results.append("✗ .ai_reference directory not found")
            return "\n".join(results)

        # 2. Check Script Index
        script_index_path = os.path.join(ai_ref_path, "script_index.json")
        script_index = None

        if os.path.exists(script_index_path):
            try:
                with open(script_index_path, 'r', encoding='utf-8') as f:
                    script_index = json.load(f)
                results.append(f"✓ Script index found with {len(script_index.get('files', {}))} files")
            except Exception as e:
                logger.error(f"Error reading script index: {str(e)}")
                results.append(f"✗ Error reading script index: {str(e)}")
                script_index = None
        else:
            results.append("✗ Script index not found")

        # 3. Check Component Registry
        component_registry_path = os.path.join(ai_ref_path, "component_registry.json")
        component_registry = None

        if os.path.exists(component_registry_path):
            try:
                with open(component_registry_path, 'r', encoding='utf-8') as f:
                    component_registry = json.load(f)
                component_count = len(component_registry.get('components', {}))
                results.append(f"✓ Component registry found with {component_count} components")
            except Exception as e:
                logger.error(f"Error reading component registry: {str(e)}")
                results.append(f"✗ Error reading component registry: {str(e)}")
                component_registry = None
        else:
            results.append("✗ Component registry not found")

        # 4. Test Component Query - Try to find a random component if registry exists
        if component_registry and component_registry.get('components'):
            try:
                # Get a random component from the registry
                components = list(component_registry.get('components', {}).keys())
                if components:
                    test_component = components[0]  # Take the first component for testing
                    results.append(f"✓ Test component found: {test_component}")

                    # Don't actually perform the search here to prevent potential output issues
                    results.append(f"✓ Component testing skipped (but component is available)")
                else:
                    results.append(f"⚠ No components found in registry to test")
            except Exception as e:
                logger.error(f"Error testing component query: {str(e)}")
                results.append(f"✗ Error testing component query: {str(e)}")
        else:
            results.append("⚠ Skipping component query test - no components available")

        # 5. Verify scripts directory
        scripts_dir = os.path.join(ai_ref_path, "scripts")
        if os.path.exists(scripts_dir):
            script_files = [f for f in os.listdir(scripts_dir) if f.endswith('.json')]
            results.append(f"✓ Scripts directory contains {len(script_files)} mini-librarian files")
        else:
            results.append("✗ Scripts directory not found")

        # 6. Check active monitoring status
        with state_lock:
            is_monitored = project_path in librarian_context["active_projects"]

        if is_monitored:
            results.append("✓ Project is actively monitored for changes")
        else:
            results.append("✗ Project is not in active monitoring list")

        # 7. Summary
        success_count = len([line for line in results if line.startswith("✓")])
        warning_count = len([line for line in results if line.startswith("⚠")])
        error_count = len([line for line in results if line.startswith("✗")])

        results.append(f"\nDiagnostic Summary: {success_count} checks passed, {warning_count} warnings, {error_count} errors")

        if error_count > 0:
            results.append("⚠ Some diagnostics failed. The librarian may have limited functionality.")
        else:
            results.append("✅ AI Librarian is fully operational!")

        # Save diagnostic report
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        report_path = os.path.join(ai_ref_path, "diagnostics", f"diagnostic-report-{timestamp}.txt")
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(results))
        except Exception as e:
            logger.error(f"Error saving diagnostic report: {str(e)}")
            # Don't add to results to avoid corruption

        return "\n".join(results)
    except Exception as e:
        logger.error(f"Error during diagnostics: {str(e)}")
        return f"Error running diagnostics: {str(e)}"

@mcp.tool()
def sanity_check(project_path: str, create_artifact: bool = False) -> str:
    """
    Run a comprehensive code quality check on the project.
    
    This tool performs a series of checks on the codebase to identify potential issues,
    inconsistencies, and path problems. It helps maintain code quality and catch
    configuration problems before they cause issues.
    
    Checks include:
    - Critical path verification
    - Import validation
    - Path reference analysis
    - Deprecated function detection
    - Duplicate functionality identification
    - Misplaced files detection
    - Static analysis with pylint (if available)
    - AI Librarian self-validation
    - Execution trace analysis
    
    Args:
        project_path: The root directory of the project to check
        create_artifact: Whether to create an artifact with the report (default: False)
        
    Returns:
        A detailed report of the sanity check results
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Check if project is accessible
            if project_path not in permission_status or not permission_status[project_path]:
                access_check = check_project_access(project_path)
                if "Permission denied" in access_check or "Error checking access" in access_check:
                    return access_check

            # Try to use the custom script first
            try:
                import subprocess

                # Run the custom script
                custom_script = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                           "scripts", "run_sanity_check.py")

                if os.path.exists(custom_script):
                    result = subprocess.run([sys.executable, custom_script, project_path],
                                          capture_output=True, text=True, check=False)
                    report = result.stdout

                    # If we got a valid report, use it
                    if "AI Dev Toolkit Sanity Check Report" in report:
                        return report

                # Fall back to the imported run_sanity_check
                logger.info("Using fallback sanity check implementation")
                report = run_sanity_check(project_path, create_artifact)
            except Exception as e:
                logger.error(f"Error running custom sanity check: {str(e)}")
                # Fall back to the imported run_sanity_check
                report = run_sanity_check(project_path, create_artifact)

            # Save a copy of the report to the diagnostics directory for future reference
            try:
                ai_ref_path = os.path.join(project_path, ".ai_reference")
                if os.path.exists(ai_ref_path):
                    diagnostics_path = os.path.join(ai_ref_path, "diagnostics")
                    if not os.path.exists(diagnostics_path):
                        os.makedirs(diagnostics_path, exist_ok=True)

                    # Save the report with timestamp
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    report_path = os.path.join(diagnostics_path, f"sanity_check_{timestamp}.md")
                    with open(report_path, 'w', encoding='utf-8') as f:
                        f.write(report)

                    logger.info(f"Saved sanity check report to {report_path}")
            except Exception as e:
                logger.warning(f"Failed to save sanity check report: {e}")

            return report
        except Exception as e:
            logger.error(f"Error running sanity check: {str(e)}")
            return f"Error running sanity check: {str(e)}"


@mcp.tool()
def add_todo(project_path: str, title: str, description: str = "", priority: str = "medium", tags: str = "", context_prompt: str = None) -> Dict[str, str]:
    """
    Add a new to-do item to the project's persistent to-do list.
    
    The to-do list is stored with the project's AI Librarian data and persists across
    conversations, allowing tasks to be remembered and tracked over time.
    
    Args:
        project_path: The root directory of the project
        title: Title of the to-do item
        description: Detailed description of the task
        priority: Priority level (low, medium, high)
        tags: Comma-separated list of tags
        context_prompt: Optional prompt to help Claude retrieve full context for this todo item
        
    Returns:
        Success message with the ID of the created to-do item
    """
    # Use monitoring pauser to prevent output corruption
    with MonitoringPauser():
        try:
            # Check if the AI Librarian exists
            ai_ref_path = os.path.join(project_path, ".ai_reference")
            if not os.path.exists(ai_ref_path):
                return {
                    "status": "error",
                    "message": f"AI Librarian not initialized at {project_path}. Run initialize_librarian first."
                }

            # Create the todo manager
            todo_manager = TodoManager(project_path)

            # Parse tags
            tag_list = [tag.strip() for tag in tags.split(",") if tag.strip()]

            # Add the to-do item
            todo_id = todo_manager.add_todo(
                title=title,
                description=description,
                priority=priority,
                tags=tag_list,
                context_prompt=context_prompt
            )
            
            # Get the created todo to check if it's a quick view item
            todo = todo_manager.get_todo(todo_id)
            is_quick_view = todo.get("context_prompt") is not None and todo.get("full_description") is not None
            
            result = {
                "status": "success",
                "todo_id": todo_id,
                "title": title,
                "priority": priority,
                "message": f"To-do item added with ID: {todo_id}"
            }
            
            # If this is a quick view todo, add a note about it
            if is_quick_view:
                result["is_quick_view"] = True
                result["context_prompt"] = todo.get("context_prompt")
                result["message"] += " (Quick view format: Full details stored in context)"
            
            return result
        except Exception as e:
            logger.error(f"Error adding to-do item: {str(e)}")
            return {
                "status": "error",
                "message": f"Error adding to-do item: {str(e)}"
            }

@mcp.tool()
def list_todos(project_path: str, status: str = "active", priority: str = None, tag: str = None) -> Dict[str, Any]:
    """
    List to-do items for the project with optional filtering.
    
    Args:
        project_path: The root directory of the project
        status: Filter by status (active, completed, etc.)
        priority: Filter by priority (low, medium, high)
        tag: Filter by a specific tag
        
    Returns:
        Formatted list of matching to-do items
    """
    # Use monitoring pauser to prevent output corruption
    with MonitoringPauser():
        try:
            # Check if the AI Librarian exists
            ai_ref_path = os.path.join(project_path, ".ai_reference")
            if not os.path.exists(ai_ref_path):
                return {
                    "status": "error",
                    "message": f"AI Librarian not initialized at {project_path}. Run initialize_librarian first."
                }

            # Create the todo manager
            todo_manager = TodoManager(project_path)

            # Get the to-do items
            todos = todo_manager.get_todos(status=status, priority=priority, tag=tag)

            if not todos:
                return {
                    "status": "success",
                    "found": False,
                    "message": f"No to-do items found with the specified filters.",
                    "filters": {
                        "status": status,
                        "priority": priority or "any",
                        "tag": tag or "any"
                    }
                }

            # Return structured results
            return {
                "status": "success",
                "found": True,
                "count": len(todos),
                "todos": todos,
                "filters": {
                    "status": status,
                    "priority": priority or "any",
                    "tag": tag or "any"
                }
            }
        except Exception as e:
            logger.error(f"Error listing to-do items: {str(e)}")
            return {
                "status": "error",
                "message": f"Error listing to-do items: {str(e)}"
            }

@mcp.tool()
def update_todo_status(project_path: str, todo_id: str, status: str) -> Dict[str, Any]:
    """
    Update the status of a to-do item.
    
    Args:
        project_path: The root directory of the project
        todo_id: ID of the to-do item to update
        status: New status (active, completed, etc.)
        
    Returns:
        Success message or error information
    """
    # Use monitoring pauser to prevent output corruption
    with MonitoringPauser():
        try:
            # Check if the AI Librarian exists
            ai_ref_path = os.path.join(project_path, ".ai_reference")
            if not os.path.exists(ai_ref_path):
                return {
                    "status": "error",
                    "message": f"AI Librarian not initialized at {project_path}. Run initialize_librarian first."
                }

            # Create the todo manager
            todo_manager = TodoManager(project_path)

            # Update the to-do item
            success = todo_manager.update_todo(todo_id, status=status)

            if success:
                return {
                    "status": "success",
                    "todo_id": todo_id,
                    "updated_status": status,
                    "message": f"Updated status of to-do item {todo_id} to '{status}'"
                }
            else:
                return {
                    "status": "error",
                    "message": f"To-do item with ID {todo_id} not found"
                }
        except Exception as e:
            logger.error(f"Error updating to-do item: {str(e)}")
            return {
                "status": "error",
                "message": f"Error updating to-do item: {str(e)}"
            }

@mcp.tool()
def add_subtask(project_path: str, todo_id: str, title: str) -> Dict[str, Any]:
    """
    Add a subtask to an existing to-do item.
    
    Args:
        project_path: The root directory of the project
        todo_id: ID of the parent to-do item
        title: Title of the subtask
        
    Returns:
        Success message or error information
    """
    # Use monitoring pauser to prevent output corruption
    with MonitoringPauser():
        try:
            # Check if the AI Librarian exists
            ai_ref_path = os.path.join(project_path, ".ai_reference")
            if not os.path.exists(ai_ref_path):
                return {
                    "status": "error",
                    "message": f"AI Librarian not initialized at {project_path}. Run initialize_librarian first."
                }

            # Create the todo manager
            todo_manager = TodoManager(project_path)

            # Add the subtask
            subtask_id = todo_manager.add_subtask(todo_id, title)

            if subtask_id:
                return {
                    "status": "success",
                    "todo_id": todo_id,
                    "subtask_id": subtask_id,
                    "title": title,
                    "message": f"Added subtask to to-do item {todo_id}"
                }
            else:
                return {
                    "status": "error",
                    "message": f"To-do item with ID {todo_id} not found"
                }
        except Exception as e:
            logger.error(f"Error adding subtask: {str(e)}")
            return {
                "status": "error",
                "message": f"Error adding subtask: {str(e)}"
            }

@mcp.tool()
def search_todos(project_path: str, query: str) -> Dict[str, Any]:
    """
    Search for to-do items by text in title or description.
    
    Args:
        project_path: The root directory of the project
        query: Search text
        
    Returns:
        Formatted list of matching to-do items
    """
    # Use monitoring pauser to prevent output corruption
    with MonitoringPauser():
        try:
            # Check if the AI Librarian exists
            ai_ref_path = os.path.join(project_path, ".ai_reference")
            if not os.path.exists(ai_ref_path):
                return {
                    "status": "error",
                    "message": f"AI Librarian not initialized at {project_path}. Run initialize_librarian first."
                }

            # Create the todo manager
            todo_manager = TodoManager(project_path)

            # Search for to-do items
            todos = todo_manager.search_todos(query)

            if not todos:
                return {
                    "status": "success",
                    "found": False,
                    "query": query,
                    "message": f"No to-do items found matching '{query}'"
                }

            # Return structured results
            return {
                "status": "success",
                "found": True,
                "query": query,
                "count": len(todos),
                "todos": todos
            }
        except Exception as e:
            logger.error(f"Error searching to-do items: {str(e)}")
            return {
                "status": "error",
                "message": f"Error searching to-do items: {str(e)}"
            }

#-----------------------------------------------------------------
# Edit Bookmark Tools
#-----------------------------------------------------------------

@mcp.tool()
def create_edit_bookmark(project_path: str, file_path: str, start_line: int, end_line: int, bookmark_name: str = None) -> Dict[str, Any]:
    """
    Create a bookmark for editing a section of a file.
    
    This tool extracts a section of a file based on line numbers and creates a temporary
    bookmark file that can be edited and later applied back to the original file.
    
    Args:
        project_path: The root directory of the project
        file_path: Path to the file to bookmark
        start_line: First line of the section to bookmark (1-based)
        end_line: Last line of the section to bookmark (inclusive)
        bookmark_name: Optional name for the bookmark
        
    Returns:
        Dictionary with bookmark information
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Initialize the edit bookmark manager
            bookmark_manager = EditBookmark(project_path)

            # Create the bookmark
            bookmark_id = bookmark_manager.create_bookmark(file_path, start_line, end_line, bookmark_name)

            # Get the content for convenience
            content = bookmark_manager.get_bookmark_content(bookmark_id)

            return {
                "status": "success",
                "bookmark_id": bookmark_id,
                "file_path": file_path,
                "start_line": start_line,
                "end_line": end_line,
                "line_count": end_line - start_line + 1,
                "content": content,
                "message": f"Created edit bookmark '{bookmark_id}' for lines {start_line}-{end_line}"
            }
        except Exception as e:
            logger.error(f"Error creating edit bookmark: {str(e)}")
            return {
                "status": "error",
                "message": f"Error creating edit bookmark: {str(e)}"
            }

@mcp.tool()
def get_bookmark_content(project_path: str, bookmark_id: str) -> Dict[str, Any]:
    """
    Get the content of an edit bookmark.
    
    Args:
        project_path: The root directory of the project
        bookmark_id: The ID of the bookmark
        
    Returns:
        Dictionary with the bookmark content
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Initialize the edit bookmark manager
            bookmark_manager = EditBookmark(project_path)

            # Get the bookmark content
            content = bookmark_manager.get_bookmark_content(bookmark_id)

            if content is None:
                return {
                    "status": "error",
                    "message": f"Bookmark not found: {bookmark_id}"
                }

            return {
                "status": "success",
                "bookmark_id": bookmark_id,
                "content": content,
                "message": f"Retrieved content for bookmark '{bookmark_id}'"
            }
        except Exception as e:
            logger.error(f"Error getting bookmark content: {str(e)}")
            return {
                "status": "error",
                "message": f"Error getting bookmark content: {str(e)}"
            }

@mcp.tool()
def update_bookmark(project_path: str, bookmark_id: str, new_content: str) -> Dict[str, Any]:
    """
    Update the content of an edit bookmark.
    
    Args:
        project_path: The root directory of the project
        bookmark_id: The ID of the bookmark
        new_content: The new content for the bookmark
        
    Returns:
        Dictionary with the result of the update operation
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Initialize the edit bookmark manager
            bookmark_manager = EditBookmark(project_path)

            # Update the bookmark
            success = bookmark_manager.update_bookmark(bookmark_id, new_content)

            if not success:
                return {
                    "status": "error",
                    "message": f"Bookmark not found: {bookmark_id}"
                }

            # Get diff if available
            diff = bookmark_manager.get_bookmark_diff(bookmark_id)

            return {
                "status": "success",
                "bookmark_id": bookmark_id,
                "diff": diff,
                "message": f"Updated content for bookmark '{bookmark_id}'"
            }
        except Exception as e:
            logger.error(f"Error updating bookmark: {str(e)}")
            return {
                "status": "error",
                "message": f"Error updating bookmark: {str(e)}"
            }

@mcp.tool()
def apply_bookmark(project_path: str, bookmark_id: str) -> Dict[str, Any]:
    """
    Apply a bookmark to the original file.
    
    This tool replaces the bookmarked section in the original file with the
    edited content from the bookmark.
    
    Args:
        project_path: The root directory of the project
        bookmark_id: The ID of the bookmark
        
    Returns:
        Dictionary with the result of the apply operation
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Initialize the edit bookmark manager
            bookmark_manager = EditBookmark(project_path)

            # Get diff before applying for reporting
            diff = bookmark_manager.get_bookmark_diff(bookmark_id)

            # Apply the bookmark
            success = bookmark_manager.apply_bookmark(bookmark_id)

            if not success:
                return {
                    "status": "error",
                    "message": f"Bookmark not found or could not be applied: {bookmark_id}"
                }

            return {
                "status": "success",
                "bookmark_id": bookmark_id,
                "diff": diff,
                "message": f"Successfully applied bookmark '{bookmark_id}' to original file"
            }
        except Exception as e:
            logger.error(f"Error applying bookmark: {str(e)}")
            return {
                "status": "error",
                "message": f"Error applying bookmark: {str(e)}"
            }

@mcp.tool()
def list_bookmarks(project_path: str) -> Dict[str, Any]:
    """
    List all active bookmarks for a project.
    
    Args:
        project_path: The root directory of the project
        
    Returns:
        Dictionary with all active bookmarks
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Initialize the edit bookmark manager
            bookmark_manager = EditBookmark(project_path)

            # List bookmarks
            bookmarks = bookmark_manager.list_bookmarks()

            if not bookmarks:
                return {
                    "status": "success",
                    "found": False,
                    "message": "No active bookmarks found for this project"
                }

            return {
                "status": "success",
                "found": True,
                "count": len(bookmarks),
                "bookmarks": bookmarks,
                "message": f"Found {len(bookmarks)} active bookmarks"
            }
        except Exception as e:
            logger.error(f"Error listing bookmarks: {str(e)}")
            return {
                "status": "error",
                "message": f"Error listing bookmarks: {str(e)}"
            }

@mcp.tool()
def remove_bookmark(project_path: str, bookmark_id: str) -> Dict[str, Any]:
    """
    Remove a bookmark.
    
    Args:
        project_path: The root directory of the project
        bookmark_id: The ID of the bookmark
        
    Returns:
        Dictionary with the result of the remove operation
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Initialize the edit bookmark manager
            bookmark_manager = EditBookmark(project_path)

            # Remove the bookmark
            success = bookmark_manager.remove_bookmark(bookmark_id)

            if not success:
                return {
                    "status": "error",
                    "message": f"Bookmark not found: {bookmark_id}"
                }

            return {
                "status": "success",
                "bookmark_id": bookmark_id,
                "message": f"Removed bookmark '{bookmark_id}'"
            }
        except Exception as e:
            logger.error(f"Error removing bookmark: {str(e)}")
            return {
                "status": "error",
                "message": f"Error removing bookmark: {str(e)}"
            }

@mcp.tool()
def read_file(path: str, encoding: str = "utf-8", use_cache: bool = True) -> Dict[str, Any]:
    """
    Read the complete contents of a file.
    
    This tool allows reading the contents of a file within the allowed directories,
    which is useful for examining code, configuration files, or documentation.
    
    For improved performance, it uses a file cache to avoid reading the same file repeatedly.
    
    Args:
        path: Path to the file to read
        encoding: File encoding (default: utf-8)
        use_cache: Whether to use the file cache (default: True)
        
    Returns:
        Dictionary with the file content and metadata
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Normalize the path
            path = os.path.abspath(path)

            # Check if path is within allowed directories
            if not any(path.startswith(allowed_dir) for allowed_dir in ALLOWED_DIRECTORIES):
                return {
                    "status": "error",
                    "message": f"Access denied: {path} is not within allowed directories"
                }

            # Check if file exists
            if not os.path.isfile(path):
                # Special case: Check if there's an index that contains info about this
                # Look for project roots that might have an .ai_reference directory
                for allowed_dir in ALLOWED_DIRECTORIES:
                    if path.startswith(allowed_dir):
                        # Check for .ai_reference in the project
                        rel_path = os.path.relpath(path, allowed_dir)
                        ai_ref_path = os.path.join(allowed_dir, ".ai_reference")
                        script_index_path = os.path.join(ai_ref_path, "script_index.json")
                        
                        if os.path.exists(script_index_path):
                            try:
                                with open(script_index_path, 'r', encoding='utf-8') as f:
                                    script_index = json.load(f)
                                
                                # Look for this path in the script index
                                if rel_path in script_index.get("files", {}):
                                    # We found a reference, suggest using indexed info
                                    return {
                                        "status": "indexed_only",
                                        "path": path,
                                        "message": f"File not found directly but exists in the index. Use index_query tool instead.",
                                        "indexed_path": rel_path,
                                        "index_location": script_index_path
                                    }
                            except Exception:
                                pass  # Continue with normal error handling
                
                return {
                    "status": "error",
                    "message": f"File not found: {path}"
                }

            # Check if we have read permission
            if not os.access(path, os.R_OK):
                return {
                    "status": "error",
                    "message": f"Permission denied: Cannot read {path}"
                }
                
            # Check cache first if enabled
            if use_cache:
                cached_data = cache_get_file(path, encoding)
                if cached_data:
                    logger.info(f"Using cached data for: {path}")
                    # Add cache hit indicator
                    result = {**cached_data}
                    result["from_cache"] = True
                    return result

            # Try to determine MIME type
            mime_type, _ = mimetypes.guess_type(path)
            if mime_type is None:
                # Default to text if we can't determine
                mime_type = "text/plain"

            # Read the file content
            try:
                with open(path, 'r', encoding=encoding) as f:
                    content = f.read()

                # Get file stats
                stats = os.stat(path)
                
                # Create result
                result = {
                    "status": "success",
                    "path": path,
                    "content": content,
                    "size": stats.st_size,
                    "mime_type": mime_type,
                    "encoding": encoding,
                    "modified": stats.st_mtime,
                    "created": stats.st_ctime,
                    "from_cache": False
                }
                
                # Add to cache if enabled
                if use_cache:
                    cache_set_file(path, result)
                
                return result
                
            except UnicodeDecodeError:
                # Try to read as binary for non-text files
                try:
                    with open(path, 'rb') as f:
                        binary_content = f.read()

                    # Create binary result
                    result = {
                        "status": "binary",
                        "path": path,
                        "size": len(binary_content),
                        "mime_type": mime_type or "application/octet-stream",
                        "encoding": "binary",
                        "message": f"Binary file detected ({len(binary_content)} bytes). Content not displayed.",
                        "from_cache": False
                    }
                    
                    # Add to cache if enabled
                    if use_cache:
                        cache_set_file(path, result)
                    
                    return result
                    
                except Exception as bin_error:
                    return {
                        "status": "error",
                        "message": f"Error reading binary file: {str(bin_error)}"
                    }
            except Exception as e:
                logger.error(f"Error reading file {path}: {str(e)}")
                return {
                    "status": "error",
                    "message": f"Error reading file: {str(e)}"
                }
        except Exception as e:
            logger.error(f"Error in read_file: {str(e)}")
            return {
                "status": "error",
                "message": f"Error reading file: {str(e)}"
            }

@mcp.tool()
def read_multiple_files(paths: List[str], use_cache: bool = True) -> Dict[str, Any]:
    """
    Read the contents of multiple files simultaneously.
    
    This is more efficient than reading files one by one when you need to analyze
    or compare multiple files. Each file's content is returned with its path as a
    reference. Failed reads for individual files won't stop the entire operation.
    
    For improved performance, it uses a file cache to avoid reading the same files repeatedly.
    
    Args:
        paths: List of file paths to read
        use_cache: Whether to use the file cache (default: True)
        
    Returns:
        Dictionary mapping file paths to their contents or error messages
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            results = {}
            cache_stats = {"hits": 0, "misses": 0, "total": len(paths)}

            for path in paths:
                try:
                    # Normalize the path
                    path = os.path.abspath(path)

                    # Check if path is within allowed directories
                    if not any(path.startswith(allowed_dir) for allowed_dir in ALLOWED_DIRECTORIES):
                        results[path] = {
                            "status": "error",
                            "message": f"Access denied: {path} is not within allowed directories"
                        }
                        continue

                    # Check if file exists
                    if not os.path.isfile(path):
                        # Check if indexed but not found directly
                        indexed = False
                        for allowed_dir in ALLOWED_DIRECTORIES:
                            if path.startswith(allowed_dir):
                                # Check for .ai_reference in the project
                                rel_path = os.path.relpath(path, allowed_dir)
                                ai_ref_path = os.path.join(allowed_dir, ".ai_reference")
                                script_index_path = os.path.join(ai_ref_path, "script_index.json")
                                
                                if os.path.exists(script_index_path):
                                    try:
                                        with open(script_index_path, 'r', encoding='utf-8') as f:
                                            script_index = json.load(f)
                                        
                                        # Look for this path in the script index
                                        if rel_path in script_index.get("files", {}):
                                            # Found in index but not on disk
                                            indexed = True
                                            results[path] = {
                                                "status": "indexed_only",
                                                "path": path,
                                                "message": f"File not found directly but exists in the index.",
                                                "indexed_path": rel_path,
                                                "index_location": script_index_path
                                            }
                                            break
                                    except Exception:
                                        pass
                        
                        if not indexed:
                            results[path] = {
                                "status": "error",
                                "message": f"File not found: {path}"
                            }
                        continue

                    # Check if we have read permission
                    if not os.access(path, os.R_OK):
                        results[path] = {
                            "status": "error",
                            "message": f"Permission denied: Cannot read {path}"
                        }
                        continue
                    
                    # Check cache first if enabled
                    if use_cache:
                        cached_data = cache_get_file(path, 'utf-8')
                        if cached_data:
                            logger.info(f"Using cached data for: {path}")
                            # Add cache hit indicator
                            result = {**cached_data}
                            result["from_cache"] = True
                            results[path] = result
                            cache_stats["hits"] += 1
                            continue
                    
                    # Cache miss, need to read the file
                    cache_stats["misses"] += 1

                    # Try to determine MIME type
                    mime_type, _ = mimetypes.guess_type(path)
                    if mime_type is None:
                        # Default to text if we can't determine
                        mime_type = "text/plain"

                    # Read the file content
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            content = f.read()

                        # Get file stats
                        stats = os.stat(path)

                        # Create result dictionary
                        result = {
                            "status": "success",
                            "content": content,
                            "size": stats.st_size,
                            "mime_type": mime_type,
                            "modified": stats.st_mtime,
                            "encoding": "utf-8",
                            "from_cache": False
                        }
                        
                        # Add to cache if enabled
                        if use_cache:
                            cache_set_file(path, result)
                            
                        results[path] = result
                        
                    except UnicodeDecodeError:
                        # Try with binary mode for non-text files
                        try:
                            with open(path, 'rb') as f:
                                binary_content = f.read()

                            # Create binary result
                            result = {
                                "status": "binary",
                                "size": len(binary_content),
                                "mime_type": mime_type or "application/octet-stream",
                                "message": f"Binary file detected ({len(binary_content)} bytes)",
                                "encoding": "binary",
                                "from_cache": False
                            }
                            
                            # Add to cache if enabled
                            if use_cache:
                                cache_set_file(path, result)
                                
                            results[path] = result
                            
                        except Exception as bin_error:
                            results[path] = {
                                "status": "error",
                                "message": f"Error reading binary file: {str(bin_error)}"
                            }
                    except Exception as e:
                        logger.error(f"Error reading file {path}: {str(e)}")
                        results[path] = {
                            "status": "error",
                            "message": f"Error reading file: {str(e)}"
                        }
                except Exception as e:
                    logger.error(f"Error processing file {path}: {str(e)}")
                    results[path] = {
                        "status": "error",
                        "message": f"Error processing file: {str(e)}"
                    }
            
            # Add cache statistics to result
            return {
                "files": results,
                "count": len(paths),
                "success_count": sum(1 for r in results.values() if r.get("status") == "success"),
                "error_count": sum(1 for r in results.values() if r.get("status") == "error"),
                "cache_hits": cache_stats["hits"],
                "cache_misses": cache_stats["misses"],
                "cache_hit_ratio": cache_stats["hits"] / len(paths) if len(paths) > 0 else 0
            }

            return {
                "status": "success",
                "count": len(paths),
                "successful_reads": sum(1 for p in results if results[p].get("status") == "success"),
                "results": results
            }
        except Exception as e:
            logger.error(f"Error in read_multiple_files: {str(e)}")
            return {
                "status": "error",
                "message": f"Error reading multiple files: {str(e)}"
            }

@mcp.tool()
def infer_todos(project_path: str, text: str) -> Dict[str, Any]:
    """
    Analyze text and extract potential to-do items, adding them to the list.
    
    This tool looks for common patterns that indicate tasks or reminders in conversation
    text and automatically adds them to the to-do list.
    
    Args:
        project_path: The root directory of the project
        text: Text to analyze for potential to-do items
        
    Returns:
        Message about extracted to-do items
    """
    # Use monitoring pauser to prevent output corruption
    with MonitoringPauser():
        try:
            # Check if the AI Librarian exists
            ai_ref_path = os.path.join(project_path, ".ai_reference")
            if not os.path.exists(ai_ref_path):
                return {
                    "status": "error",
                    "message": f"AI Librarian not initialized at {project_path}. Run initialize_librarian first."
                }

            # Create the todo manager
            todo_manager = TodoManager(project_path)

            # Infer to-do items
            todo_item = todo_manager.infer_todo_item(text)

            if not todo_item:
                return {
                    "status": "success",
                    "found": False,
                    "message": "No potential to-do items found in the text."
                }

            # Add the inferred to-do item
            todo_id = todo_manager.add_todo(
                title=todo_item['title'],
                description=todo_item['description'],
                priority="medium"
            )

            return {
                "status": "success",
                "found": True,
                "todo_id": todo_id,
                "title": todo_item['title'],
                "description": todo_item.get('description', ''),
                "message": f"Extracted and added to-do item with ID: {todo_id}"
            }
        except Exception as e:
            logger.error(f"Error inferring to-do items: {str(e)}")
            return {
                "status": "error",
                "message": f"Error inferring to-do items: {str(e)}"
            }

@mcp.tool()
def edit_file(path: str, old_text: str, new_text: str, encoding: str = "utf-8") -> Dict[str, Any]:
    """
    Edit a file by replacing a specific text segment with new text.
    
    This tool allows for targeted modifications to files without rewriting the entire content,
    which is useful for making small changes or updates to configuration files, code, or documentation.
    
    Args:
        path: Path to the file to edit
        old_text: The text segment to be replaced (must match exactly)
        new_text: The new text to replace with
        encoding: File encoding (default: utf-8)
        
    Returns:
        Dictionary with the result of the edit operation, including a git-style diff
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Normalize the path
            path = os.path.abspath(path)

            # Validate path using the improved validate_path function
            if not validate_path(path, ALLOWED_DIRECTORIES):
                return {
                    "status": "error",
                    "message": f"Access denied: {path} is not within allowed directories"
                }

            # Check if file exists
            if not os.path.isfile(path):
                return {
                    "status": "error",
                    "message": f"File not found: {path}"
                }

            # Check if we have read and write permission
            if not os.access(path, os.R_OK | os.W_OK):
                return {
                    "status": "error",
                    "message": f"Permission denied: Cannot modify {path}"
                }

            # If we get here, we're using the fallback implementation
            # Let's add some logging and minor improvements to the original method

            # Check file size before trying to read (for logging)
            try:
                file_size = os.path.getsize(path)
                logger.info(f"File size: {file_size} bytes")

                # Add a size limit for very large files
                MAX_SIZE = 50 * 1024 * 1024  # 50 MB
                if file_size > MAX_SIZE:
                    logger.warning(f"File too large: {file_size} bytes exceeds limit of {MAX_SIZE} bytes")
                    return {
                        "status": "error",
                        "message": f"File too large: {file_size / 1024 / 1024:.2f} MB exceeds limit of {MAX_SIZE / 1024 / 1024} MB"
                    }
            except Exception as e:
                logger.error(f"Error checking file size: {str(e)}")

            # Read the current content of the file
            try:
                logger.info("Reading file content")
                with open(path, 'r', encoding=encoding) as f:
                    content = f.read()
                logger.info(f"File content read, length: {len(content)} characters")
            except UnicodeDecodeError as ude:
                logger.error(f"Unicode decode error: {str(ude)}")
                return {
                    "status": "error",
                    "message": f"Cannot edit binary file or file with encoding different from {encoding}"
                }
            except Exception as e:
                logger.error(f"Error reading file: {str(e)}")
                return {
                    "status": "error",
                    "message": f"Error reading file: {str(e)}"
                }

            # Check if the old_text exists in the content
            if old_text not in content:
                logger.warning("The specified text segment was not found in the file")
                return {
                    "status": "error",
                    "message": f"The specified text segment was not found in the file"
                }

            # Check if the old text occurs multiple times (ambiguous replacement)
            occurrences = content.count(old_text)
            if occurrences > 1:
                logger.warning(f"Text segment appears multiple times in file ({occurrences} occurrences)")
                return {
                    "status": "error",
                    "message": f"The specified text segment appears {occurrences} times in the file. Please provide a more specific text segment."
                }

            # Replace the text
            logger.info("Performing text replacement")
            new_content = content.replace(old_text, new_text)

            # Calculate a more descriptive diff for the response
            old_lines = old_text.splitlines()
            new_lines = new_text.splitlines()

            # Generate a unified diff-like output
            diff = ["Changes:"]
            diff.append(f"--- {path} (original)")
            diff.append(f"+++ {path} (modified)")

            # Add the changed lines with line numbers if possible
            try:
                # Find where in the file the old_text is located
                lines_before = content.split(old_text, 1)[0].count('\n') + 1

                # Add a better header for the diff
                diff.append(f"@@ -{lines_before},{len(old_lines)} +{lines_before},{len(new_lines)} @@")

                for line in old_lines:
                    diff.append(f"- {line}")
                for line in new_lines:
                    diff.append(f"+ {line}")
            except Exception as e:
                logger.error(f"Error generating diff: {str(e)}")
                # Fall back to a simple diff message
                diff = ["Changes: (detailed diff not available)"]

            # Create the directory if it doesn't exist
            dir_name = os.path.dirname(path)
            if dir_name and not os.path.exists(dir_name):
                try:
                    logger.info(f"Creating directory: {dir_name}")
                    os.makedirs(dir_name, exist_ok=True)
                except OSError as e:
                    logger.error(f"Cannot create directory {dir_name}: {str(e)}")
                    return {
                        "status": "error",
                        "message": f"Cannot create directory {dir_name}: {str(e)}"
                    }

            # Create a temporary file in the system temp directory instead of target directory
            # to avoid potential permission issues
            logger.info("Creating temporary file in system temp directory")
            temp_fd, temp_path = tempfile.mkstemp(suffix='.tmp')
            os.close(temp_fd)  # Close the file descriptor

            # Write the modified content to the temporary file
            try:
                with open(temp_path, 'w', encoding=encoding) as temp_file:
                    temp_file.write(new_content)

                logger.info(f"Copying {temp_path} to {path}")
                # Use copy2 which preserves file metadata
                shutil.copy2(temp_path, path)

                # Remove the temporary file after successful copy
                try:
                    logger.info(f"Removing temporary file: {temp_path}")
                    os.unlink(temp_path)
                except Exception as cleanup_error:
                    logger.warning(f"Could not remove temporary file {temp_path}: {str(cleanup_error)}")

                logger.info(f"Successfully edited file: {path}")

                # Calculate the character and line differences for better reporting
                chars_removed = len(old_text)
                chars_added = len(new_text)
                lines_removed = len(old_lines)
                lines_added = len(new_lines)

                # Create hash instead of using built-in hash function for better consistency
                import hashlib
                content_hash_before = hashlib.md5(content.encode()).hexdigest()
                content_hash_after = hashlib.md5(new_content.encode()).hexdigest()

                return {
                    "status": "success",
                    "message": f"Successfully edited file: {path}",
                    "diff": "\n".join(diff),
                    "path": path,
                    "encoding": encoding,
                    "stats": {
                        "chars_removed": chars_removed,
                        "chars_added": chars_added,
                        "chars_net_change": chars_added - chars_removed,
                        "lines_removed": lines_removed,
                        "lines_added": lines_added,
                        "lines_net_change": lines_added - lines_removed
                    },
                    "content_hash_before": content_hash_before,
                    "content_hash_after": content_hash_after
                }

            except Exception as e:
                # Clean up the temporary file if it exists
                if os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except Exception as cleanup_error:
                        logger.error(f"Error cleaning up temp file: {str(cleanup_error)}")

                logger.error(f"Error writing to file {path}: {str(e)}")
                return {
                    "status": "error",
                    "message": f"Error writing file: {str(e)}"
                }
        except Exception as e:
            logger.error(f"Error editing file: {str(e)}")
            return {
                "status": "error",
                "message": f"Error editing file: {str(e)}"
            }

@mcp.tool()
def enhanced_edit_file(path: str, old_text: str, new_text: str, encoding: str = "utf-8") -> Dict[str, Any]:
    """
    Edit a file by replacing a specific text segment with new text (enhanced version).
    
    This enhanced tool allows for targeted modifications to files without rewriting the entire content.
    It includes improved error handling, better path validation, and atomic write operations.
    
    Args:
        path: Path to the file to edit
        old_text: The text segment to be replaced (must match exactly)
        new_text: The new text to replace with
        encoding: File encoding (default: utf-8)
        
    Returns:
        Dictionary with the result of the edit operation, including a git-style diff
    """
    # Import the fixed implementation
    try:
        from aitoolkit.librarian.enhanced_edit_file_fix import enhanced_edit_file_fixed
        return enhanced_edit_file_fixed(path, old_text, new_text, encoding, ALLOWED_DIRECTORIES, logger)
    except ImportError:
        logger.warning("Could not import enhanced_edit_file_fix, falling back to default implementation")

    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Normalize the path
            path = os.path.abspath(path)
            logger.info(f"Starting enhanced_edit_file for {path}")

            # Check if path is within allowed directories
            if not validate_path(path, ALLOWED_DIRECTORIES):
                return {
                    "status": "error",
                    "message": f"Access denied: {path} is not within allowed directories"
                }

            # Check if file exists
            if not os.path.isfile(path):
                return {
                    "status": "error",
                    "message": f"File not found: {path}"
                }

            # Check if we have read and write permission
            if not os.access(path, os.R_OK | os.W_OK):
                return {
                    "status": "error",
                    "message": f"Permission denied: Cannot modify {path}"
                }

            # Read the current content of the file
            try:
                with open(path, 'r', encoding=encoding) as f:
                    content = f.read()
            except UnicodeDecodeError:
                return {
                    "status": "error",
                    "message": f"Cannot edit binary file or file with encoding different from {encoding}"
                }

            # Check if the old_text exists in the content
            if old_text not in content:
                return {
                    "status": "error",
                    "message": f"The specified text segment was not found in the file"
                }

            # Check if the old_text appears multiple times
            if content.count(old_text) > 1:
                return {
                    "status": "error",
                    "message": f"The specified text segment appears multiple times in the file. Please provide a more specific text segment."
                }

            # Replace the text
            new_content = content.replace(old_text, new_text)

            # Calculate a more comprehensive diff for the response
            old_lines = old_text.splitlines()
            new_lines = new_text.splitlines()

            # Generate a unified diff-like output
            diff = ["Changes to be made:"]
            diff.append(f"--- {path} (original)")
            diff.append(f"+++ {path} (modified)")

            # Add the changed lines
            diff.append(f"@@ -1,{len(old_lines)} +1,{len(new_lines)} @@")
            for line in old_lines:
                diff.append(f"- {line}")
            for line in new_lines:
                diff.append(f"+ {line}")

            # Write the modified content to the file using atomic write pattern
            try:
                # Create a temporary file in the same directory
                dir_name = os.path.dirname(path) or "."
                with tempfile.NamedTemporaryFile(mode='w', encoding=encoding,
                                               dir=dir_name, delete=False) as temp_file:
                    temp_file.write(new_content)
                    temp_path = temp_file.name

                # Rename the temporary file to the target path (atomic operation)
                shutil.move(temp_path, path)

                logger.info(f"Successfully edited file: {path}")

                return {
                    "status": "success",
                    "message": f"Successfully edited file: {path}",
                    "diff": "\n".join(diff),
                    "path": path,
                    "encoding": encoding,
                    "old_text_length": len(old_text),
                    "new_text_length": len(new_text),
                    "change_location": content.find(old_text)
                }

            except Exception as e:
                # Clean up the temporary file if it exists
                if 'temp_path' in locals() and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except:
                        pass

                logger.error(f"Error writing to file {path}: {str(e)}")
                return {
                    "status": "error",
                    "message": f"Error writing file: {str(e)}"
                }
        except Exception as e:
            logger.error(f"Error editing file: {str(e)}")
            return {
                "status": "error",
                "message": f"Error editing file: {str(e)}"
            }

@mcp.tool()
def move_file(source: str, destination: str) -> Dict[str, Any]:
    """
    Move or rename a file or directory.
    
    This tool allows for safely moving files and directories within allowed directories,
    which is useful for reorganizing code, refactoring, and renaming files.
    
    Args:
        source: Path to the source file or directory
        destination: Path to the destination file or directory
        
    Returns:
        Dictionary with the result of the move operation
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Normalize the paths
            source_path = os.path.abspath(source)
            dest_path = os.path.abspath(destination)

            # Validate source path
            if not validate_path(source_path, ALLOWED_DIRECTORIES):
                return {
                    "status": "error",
                    "message": f"Access denied: {source} is not within allowed directories"
                }

            # Validate destination path
            if not validate_path(dest_path, ALLOWED_DIRECTORIES):
                return {
                    "status": "error",
                    "message": f"Access denied: {destination} is not within allowed directories"
                }

            # Check if source exists
            if not os.path.exists(source_path):
                return {
                    "status": "error",
                    "message": f"Source not found: {source}"
                }

            # Check if we have read and write permission on source
            if not os.access(source_path, os.R_OK | os.W_OK):
                return {
                    "status": "error",
                    "message": f"Permission denied: Cannot access {source}"
                }

            # Create destination directory if it doesn't exist
            dest_dir = os.path.dirname(dest_path)
            if dest_dir and not os.path.exists(dest_dir):
                try:
                    os.makedirs(dest_dir, exist_ok=True)
                except OSError as e:
                    return {
                        "status": "error",
                        "message": f"Cannot create destination directory {dest_dir}: {str(e)}"
                    }

            # Check if we have write permission on destination directory
            if not os.access(dest_dir or ".", os.W_OK):
                return {
                    "status": "error",
                    "message": f"Permission denied: Cannot write to destination directory"
                }

            # Check if destination already exists
            if os.path.exists(dest_path):
                return {
                    "status": "error",
                    "message": f"Destination already exists: {destination}"
                }

            # Move the file or directory
            try:
                shutil.move(source_path, dest_path)
                logger.info(f"Successfully moved {source_path} to {dest_path}")

                # Determine if it was a file or directory that was moved
                is_dir = os.path.isdir(dest_path)
                entity_type = "directory" if is_dir else "file"

                return {
                    "status": "success",
                    "message": f"Successfully moved {entity_type}: {source} → {destination}",
                    "source": source,
                    "destination": destination,
                    "type": entity_type
                }
            except Exception as e:
                logger.error(f"Error moving {source_path} to {dest_path}: {str(e)}")
                return {
                    "status": "error",
                    "message": f"Error moving file: {str(e)}"
                }
        except Exception as e:
            logger.error(f"Error in move_file: {str(e)}")
            return {
                "status": "error",
                "message": f"Error in move_file: {str(e)}"
            }

@mcp.tool()
def search_files(path: str, pattern: str, file_pattern: str = None, excludePatterns: List[str] = None, search_type: str = "both") -> Dict[str, Any]:
    """
    Recursively search for files and directories matching a pattern.
    
    This tool searches through all subdirectories from the starting path, finding files
    and directories that match the specified pattern. It can also exclude items matching
    certain patterns.
    
    For improved performance, it first checks the AI Librarian index if available.
    
    Args:
        path: The starting directory path to search in
        pattern: The search pattern to match (case-insensitive)
        file_pattern: Optional pattern to filter files (e.g., "*.py")
        excludePatterns: Optional list of patterns to exclude from results
        search_type: Type of search - "names" (file/dir names), "content" (file contents), or "both" (default)
        
    Returns:
        Dictionary with search results
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Normalize path
            search_path = os.path.abspath(path)

            # Validate path
            if not validate_path(search_path, ALLOWED_DIRECTORIES):
                return {
                    "status": "error",
                    "message": f"Access denied: {path} is not within allowed directories"
                }

            # Check if directory exists
            if not os.path.exists(search_path):
                return {
                    "status": "error",
                    "message": f"Directory not found: {path}"
                }

            # Check if path is a directory
            if not os.path.isdir(search_path):
                return {
                    "status": "error",
                    "message": f"Not a directory: {path}"
                }

            # Ensure excludePatterns is a list
            exclude_patterns = excludePatterns or []

            # Convert pattern to lowercase for case-insensitive matching
            pattern_lower = pattern.lower()
            
            # Check AI Librarian index first if available to improve performance
            ai_ref_path = os.path.join(search_path, ".ai_reference")
            script_index_path = os.path.join(ai_ref_path, "script_index.json")
            
            # Check if we have an index to use
            if os.path.exists(script_index_path):
                logger.info(f"Using AI Librarian index for search: {pattern}")
                try:
                    with open(script_index_path, 'r', encoding='utf-8') as f:
                        script_index = json.load(f)
                    
                    # Quick search through the index
                    matches = []
                    
                    # Filter based on file pattern if provided
                    pattern_matcher = None
                    if file_pattern:
                        pattern_matcher = lambda p: fnmatch.fnmatch(p.lower(), file_pattern.lower())
                    
                    # Check each indexed file
                    for rel_file_path, file_info in script_index.get("files", {}).items():
                        # Skip excluded paths
                        if any(fnmatch.fnmatch(rel_file_path.lower(), exclude.lower()) for exclude in exclude_patterns):
                            continue
                            
                        # Apply file pattern filter if provided
                        if pattern_matcher and not pattern_matcher(rel_file_path):
                            continue
                            
                        # Check if the pattern is in the file path
                        if pattern_lower in rel_file_path.lower():
                            matches.append(rel_file_path)
                            continue
                            
                        # Check if pattern matches any class or function
                        if any(pattern_lower in cls.lower() for cls in file_info.get("classes", [])) or \
                           any(pattern_lower in func.lower() for func in file_info.get("functions", [])):
                            matches.append(rel_file_path)
                    
                    if matches:
                        logger.info(f"Found {len(matches)} matches using index")
                        return {
                            "status": "success",
                            "path": path,
                            "pattern": pattern,
                            "excludePatterns": exclude_patterns,
                            "matches": matches,
                            "count": len(matches),
                            "source": "ai_reference_index",
                            "message": f"Found {len(matches)} matching files in {path} (via index)"
                        }
                    else:
                        logger.info("No matches found in index, falling back to filesystem search")
                except Exception as index_error:
                    logger.warning(f"Error using index for search: {str(index_error)}, falling back to filesystem search")
            
            # Define function to check if a path should be excluded
            def should_exclude(item_path):
                base_name = os.path.basename(item_path)
                # Check if matches any exclude patterns
                for exclude in exclude_patterns:
                    if fnmatch.fnmatch(base_name.lower(), exclude.lower()):
                        return True
                    # Also check if parent directory matches exclude pattern
                    if any(fnmatch.fnmatch(part.lower(), exclude.lower())
                           for part in Path(item_path).parts):
                        return True
                # Skip common directories and hidden files/dirs by default
                if base_name.startswith('.') or base_name in ['__pycache__', 'node_modules', '.git', 'venv', 'env']:
                    return True
                return False

            # Fallback: Collect matching files with filesystem walk
            logger.info(f"Performing filesystem search for: {pattern}")
            matches = []

            for root, dirs, files in os.walk(search_path):
                # Filter out directories that should be excluded
                # This modifies dirs in-place to avoid traversing excluded dirs
                dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d))]

                # Check files that match the pattern
                for file in files:
                    file_path = os.path.join(root, file)
                    if pattern_lower in file.lower() and not should_exclude(file_path):
                        # Return path relative to the search directory
                        rel_path = os.path.relpath(file_path, search_path)
                        matches.append(rel_path)

            # Return the results
            return {
                "status": "success",
                "path": path,
                "pattern": pattern,
                "excludePatterns": exclude_patterns,
                "matches": matches,
                "count": len(matches),
                "source": "filesystem_walk",
                "message": f"Found {len(matches)} matching files in {path}"
            }
        except Exception as e:
            logger.error(f"Error searching files: {str(e)}")
            return {
                "status": "error",
                "message": f"Error searching files: {str(e)}"
            }

@mcp.tool()
def write_file(path: str, content: str, encoding: str = "utf-8") -> Dict[str, Any]:
    """
    Create a new file or completely overwrite an existing file with new content.
    
    This tool allows for creating new files or completely replacing the content of existing files,
    which is different from the edit functions that only modify portions of files.
    
    Args:
        path: Path where the file should be written
        content: Content to write to the file
        encoding: File encoding (default: utf-8)
        
    Returns:
        Dictionary with the result of the write operation
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Normalize the path
            file_path = os.path.abspath(path)

            # Validate path
            if not validate_path(file_path, ALLOWED_DIRECTORIES):
                return {
                    "status": "error",
                    "message": f"Access denied: {path} is not within allowed directories"
                }

            # Create the directory if it doesn't exist
            dir_name = os.path.dirname(file_path)
            if dir_name and not os.path.exists(dir_name):
                try:
                    os.makedirs(dir_name, exist_ok=True)
                except OSError as e:
                    return {
                        "status": "error",
                        "message": f"Cannot create directory {dir_name}: {str(e)}"
                    }

            # Check if we have write permission to the directory
            if not os.access(dir_name or ".", os.W_OK):
                return {
                    "status": "error",
                    "message": f"Permission denied: Cannot write to directory {dir_name}"
                }

            # If the file exists, check if we have write permission
            if os.path.exists(file_path) and not os.access(file_path, os.W_OK):
                return {
                    "status": "error",
                    "message": f"Permission denied: Cannot modify {path}"
                }

            # Write the file using atomic write pattern
            try:
                # Create a temporary file in the same directory
                with tempfile.NamedTemporaryFile(mode='w', encoding=encoding,
                                              dir=dir_name or ".", delete=False) as temp_file:
                    temp_file.write(content)
                    temp_path = temp_file.name

                # Rename the temporary file to the target path (atomic operation)
                shutil.move(temp_path, file_path)

                # Get file stats
                stats = os.stat(file_path)

                # Determine if this was a create or overwrite operation
                operation = "Updated" if os.path.exists(file_path) else "Created"

                logger.info(f"Successfully wrote to file: {file_path}")

                return {
                    "status": "success",
                    "message": f"Successfully wrote {len(content)} characters to {path}",
                    "path": path,
                    "size": stats.st_size,
                    "encoding": encoding,
                    "operation": operation,
                    "bytes_written": len(content.encode(encoding))
                }

            except Exception as e:
                # Clean up the temporary file if it exists
                if 'temp_path' in locals() and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except:
                        pass

                logger.error(f"Error writing to file {file_path}: {str(e)}")
                return {
                    "status": "error",
                    "message": f"Error writing file: {str(e)}"
                }
        except Exception as e:
            logger.error(f"Error in write_file: {str(e)}")
            return {
                "status": "error",
                "message": f"Error writing file: {str(e)}"
            }

@mcp.tool()
def find_related_files(project_path: str, file_path: str) -> Dict[str, Any]:
    """
    Find files that are related to a specific file in the project.
    
    This tool analyzes the project structure to find files that are related to the 
    specified file through imports, class/function references, naming patterns, 
    or module/package relationships.
    
    Args:
        project_path: The root directory of the project
        file_path: The file to find related files for (absolute or relative to project_path)
        
    Returns:
        Dictionary with related files organized by relationship type
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            logger.debug(f"Starting find_related_files for {file_path} in {project_path}")
            
            # Normalize paths
            project_path = os.path.abspath(project_path)

            # Convert file_path to absolute path if it's relative
            if not os.path.isabs(file_path):
                file_path = os.path.join(project_path, file_path)
            file_path = os.path.abspath(file_path)

            # Validate paths
            if not validate_path(project_path, ALLOWED_DIRECTORIES):
                return {
                    "status": "error",
                    "message": f"Access denied: {project_path} is not within allowed directories"
                }

            if not validate_path(file_path, ALLOWED_DIRECTORIES):
                return {
                    "status": "error",
                    "message": f"Access denied: {file_path} is not within allowed directories"
                }

            # Check if file exists
            if not os.path.isfile(file_path):
                return {
                    "status": "error",
                    "message": f"File not found: {file_path}"
                }

            # Get relative path for cleaner output
            rel_file_path = os.path.relpath(file_path, project_path)
            logger.debug(f"Working with relative file path: {rel_file_path}")

            # Initialize result structure
            related_files = {
                "imports": [],        # Files that import the target file
                "imported_by": [],    # Files imported by the target file
                "name_related": [],   # Files with similar names
                "package_related": [], # Files in the same package
                "class_references": [], # Files that reference classes from the target file
                "function_calls": []  # Files that call functions from the target file
            }

            # Check if AI Librarian has been initialized
            ai_ref_path = os.path.join(project_path, ".ai_reference")
            if not os.path.exists(ai_ref_path):
                return {
                    "status": "error",
                    "message": f"AI Librarian not initialized for {project_path}. Run initialize_librarian first."
                }

            # Get script index
            script_index_path = os.path.join(ai_ref_path, "script_index.json")
            if not os.path.exists(script_index_path):
                return {
                    "status": "error",
                    "message": f"Script index not found at {script_index_path}."
                }

            # Safely load the script index
            try:
                with open(script_index_path, 'r', encoding='utf-8') as f:
                    script_index = json.load(f)
            except Exception as e:
                logger.error(f"Error loading script index: {str(e)}")
                return {
                    "status": "error",
                    "message": f"Error loading script index: {str(e)}"
                }

            # Get component registry
            component_registry_path = os.path.join(ai_ref_path, "component_registry.json")
            if not os.path.exists(component_registry_path):
                return {
                    "status": "error",
                    "message": f"Component registry not found at {component_registry_path}."
                }

            try:
                with open(component_registry_path, 'r', encoding='utf-8') as f:
                    component_registry = json.load(f)
                
                # Verify proper structure
                if not isinstance(component_registry, dict):
                    logger.error(f"Component registry is not a dictionary: {component_registry_path}")
                    component_registry = {"components": {}}
            except Exception as e:
                logger.error(f"Error loading component registry: {str(e)}")
                component_registry = {"components": {}}

            # Parse the target file to get its imports, classes, and functions
            target_file_info = None
            target_file_rel_path = rel_file_path.replace("\\", "/")
            logger.debug(f"Normalized target path: {target_file_rel_path}")

            # Properly check if script_index is a dictionary and has the "files" key
            if isinstance(script_index, dict) and "files" in script_index and isinstance(script_index["files"], dict):
                for path, info in script_index["files"].items():
                    if path == target_file_rel_path:
                        target_file_info = info
                        break

            if not target_file_info:
                # If the file is not in the index, parse it directly
                logger.debug(f"File not found in index, parsing directly: {file_path}")
                target_file_info = {
                    "path": target_file_rel_path,
                    "classes": [],
                    "functions": [],
                    "imports": []
                }

                try:
                    file_structure = parse_python_file(file_path)
                    target_file_info["classes"] = file_structure["classes"]
                    target_file_info["functions"] = file_structure["functions"]
                    target_file_info["imports"] = file_structure["imports"]
                except Exception as e:
                    logger.error(f"Error parsing target file {file_path}: {str(e)}")

            # Get imports from the target file
            target_imports = []
            mini_librarian_path = None

            if "mini_librarian" in target_file_info:
                mini_librarian_path = os.path.join(ai_ref_path, target_file_info["mini_librarian"])
                if os.path.exists(mini_librarian_path):
                    try:
                        with open(mini_librarian_path, 'r', encoding='utf-8') as f:
                            mini_librarian = json.load(f)
                            if isinstance(mini_librarian, dict) and "imports" in mini_librarian:
                                if isinstance(mini_librarian["imports"], list):
                                    target_imports = mini_librarian["imports"]
                                else:
                                    logger.warning(f"Imports is not a list in {mini_librarian_path}")
                    except Exception as e:
                        logger.error(f"Error reading mini librarian at {mini_librarian_path}: {str(e)}")

            # For each file in the script index, check for relationships
            # Only proceed if script_index has the proper structure
            if not (isinstance(script_index, dict) and "files" in script_index and isinstance(script_index["files"], dict)):
                return {
                    "status": "error",
                    "message": "Invalid script index structure"
                }
            
            # Process each file in the script index
            logger.debug(f"Processing {len(script_index['files'])} files for relationships")
            for path, info in script_index["files"].items():
                # Skip the target file itself
                if path == target_file_rel_path:
                    continue

                full_path = os.path.join(project_path, path)

                # 1. Package relationship
                if os.path.dirname(path) == os.path.dirname(target_file_rel_path):
                    related_files["package_related"].append({
                        "path": path,
                        "relationship": "same_package"
                    })

                # 2. Name relationship
                target_name = os.path.splitext(os.path.basename(target_file_rel_path))[0]
                file_name = os.path.splitext(os.path.basename(path))[0]

                # Check for name similarities
                if (target_name in file_name or
                    file_name in target_name or
                    file_name.startswith(target_name) or
                    target_name.startswith(file_name)):
                    related_files["name_related"].append({
                        "path": path,
                        "relationship": "similar_name"
                    })

                # 3. Check if this file imports the target file or is imported by it
                mini_librarian_path = None
                if isinstance(info, dict) and "mini_librarian" in info:
                    mini_librarian_path = os.path.join(ai_ref_path, info["mini_librarian"])

                if mini_librarian_path and os.path.exists(mini_librarian_path):
                    try:
                        with open(mini_librarian_path, 'r', encoding='utf-8') as f:
                            mini_librarian = json.load(f)

                            # Safely check for imports
                            if isinstance(mini_librarian, dict) and "imports" in mini_librarian:
                                # 3a. Check if this file imports the target file
                                try:
                                    # Check if this file imports the target file
                                    target_module = os.path.splitext(target_file_rel_path)[0].replace("/", ".")
                                    
                                    # Guard against non-string target_module or bad module names
                                    if not isinstance(target_module, str) or not target_module:
                                        logger.error(f"Invalid target module name: {target_module}")
                                        continue
                                    
                                    # Make sure os.path.basename returns a string
                                    target_basename = os.path.basename(target_module)
                                    if not isinstance(target_basename, str) or not target_basename:
                                        logger.error(f"Invalid target basename: {target_basename}")
                                        continue
                                    
                                    # Process each import, but only if imports is a list
                                    if isinstance(mini_librarian["imports"], list):
                                        for imp in mini_librarian["imports"]:
                                            # Make sure imp is a string
                                            if not isinstance(imp, str):
                                                logger.debug(f"Skipping non-string import: {type(imp)}")
                                                continue
                                            
                                            # Compare imports directly and safely check endswith
                                            matches_direct = imp == target_module
                                            matches_relative = False
                                            
                                            # Safely check if imp ends with ".target_basename"
                                            if isinstance(imp, str) and isinstance(target_basename, str):
                                                suffix = "." + target_basename
                                                if imp.endswith(suffix):
                                                    matches_relative = True
                                            
                                            if matches_direct or matches_relative:
                                                related_files["imports"].append({
                                                    "path": path,
                                                    "relationship": "imports_target",
                                                    "import_statement": imp
                                                })
                                                break
                                except Exception as e:
                                    logger.error(f"Error checking imports: {str(e)}")
                                    continue

                                # 3b. Check if the target file imports this file
                                try:
                                    # Only process if target_imports is a list
                                    if not isinstance(target_imports, list):
                                        logger.debug(f"Skipping target imports check - not a list: {type(target_imports)}")
                                        continue
                                    
                                    # Check if the target file imports this file
                                    this_module = os.path.splitext(path)[0].replace("/", ".")
                                    
                                    # Guard against non-string this_module
                                    if not isinstance(this_module, str) or not this_module:
                                        logger.error(f"Invalid module name: {this_module}")
                                        continue
                                    
                                    this_basename = os.path.basename(this_module)
                                    if not isinstance(this_basename, str) or not this_basename:
                                        logger.error(f"Invalid basename: {this_basename}")
                                        continue
                                    
                                    for imp in target_imports:
                                        # Make sure imp is a string
                                        if not isinstance(imp, str):
                                            logger.debug(f"Skipping non-string target import: {type(imp)}")
                                            continue
                                        
                                        # Compare imports directly and safely check endswith
                                        matches_direct = imp == this_module
                                        matches_relative = False
                                        
                                        # Safely check if imp ends with ".this_basename"
                                        if isinstance(imp, str) and isinstance(this_basename, str):
                                            suffix = "." + this_basename
                                            if imp.endswith(suffix):
                                                matches_relative = True
                                        
                                        if matches_direct or matches_relative:
                                            related_files["imported_by"].append({
                                                "path": path,
                                                "relationship": "imported_by_target",
                                                "import_statement": imp
                                            })
                                            break
                                except Exception as e:
                                    logger.error(f"Error checking target imports: {str(e)}")
                                    continue
                    except Exception as e:
                        logger.error(f"Error processing mini librarian for {path}: {str(e)}")
                        continue

                # 4. Class and function references
                if "classes" in target_file_info and isinstance(target_file_info["classes"], list):
                    # Check if this file references classes from the target file
                    full_content = ""
                    try:
                        with open(full_path, 'r', encoding='utf-8') as f:
                            full_content = f.read()
                    except Exception as e:
                        logger.error(f"Error reading file {full_path}: {str(e)}")

                    if full_content:
                        for class_name in target_file_info["classes"]:
                            if isinstance(class_name, str) and class_name in full_content:
                                # Verify it's a proper reference, not just string matching
                                # Look for patterns like: ClassName(, ClassName., = ClassName
                                try:
                                    import re
                                    if re.search(r'[(\s=.]' + re.escape(class_name) + r'[\s(.]', full_content):
                                        related_files["class_references"].append({
                                            "path": path,
                                            "relationship": "references_class",
                                            "class_name": class_name
                                        })
                                except Exception as e:
                                    logger.error(f"Error in regex search for class {class_name}: {str(e)}")

                    # Check for function calls
                    if "functions" in target_file_info and isinstance(target_file_info["functions"], list):
                        for func_name in target_file_info["functions"]:
                            if isinstance(func_name, str) and func_name in full_content:
                                # Look for pattern like function_name(
                                try:
                                    import re
                                    if re.search(r'[(\s=.]' + re.escape(func_name) + r'\s*\(', full_content):
                                        related_files["function_calls"].append({
                                            "path": path,
                                            "relationship": "calls_function",
                                            "function_name": func_name
                                        })
                                except Exception as e:
                                    logger.error(f"Error in regex search for function {func_name}: {str(e)}")

            # Count total related files
            total_related = sum(len(files) for files in related_files.values())

            # Create unique list by removing duplicates
            unique_related = set()
            for category, files in related_files.items():
                for file_info in files:
                    if isinstance(file_info, dict) and "path" in file_info:
                        unique_related.add(file_info["path"])

            logger.debug(f"Found {len(unique_related)} unique related files")
            return {
                "status": "success",
                "file": rel_file_path,
                "related_files": related_files,
                "total_related": total_related,
                "unique_related": len(unique_related),
                "message": f"Found {len(unique_related)} unique files related to {rel_file_path}"
            }

        except Exception as e:
            logger.error(f"Error finding related files: {str(e)}")
            return {
                "status": "error",
                "message": f"Error finding related files: {str(e)}"
            }

# Helper function for path validation
def validate_path(path: str, allowed_directories: List[str]) -> bool:
    """
    Validate that a path is within allowed directories.
    
    Args:
        path: Path to validate
        allowed_directories: List of allowed directory paths
        
    Returns:
        True if path is valid, False otherwise
    """
    # Convert to absolute path
    abs_path = os.path.abspath(path)

    # Convert all allowed directories to absolute paths
    abs_allowed = [os.path.abspath(d) for d in allowed_directories]

    # Check if the path is within any allowed directory
    for allowed_dir in abs_allowed:
        # Use pathlib for safer path comparison
        path_obj = Path(abs_path)
        allowed_obj = Path(allowed_dir)

        try:
            # Use relative_to to check if the path is inside the allowed dir
            # This will raise ValueError if path is not within allowed_dir
            path_obj.relative_to(allowed_obj)
            return True
        except ValueError:
            # Path is not within this allowed dir, try the next one
            continue

    # If we get here, the path is not within any allowed directory
    return False

@mcp.tool()
def create_directory(path: str) -> Dict[str, Any]:
    """
    Create a new directory or ensure a directory exists.
    
    Can create multiple nested directories in one operation. If the directory already exists,
    this operation will succeed silently. Perfect for setting up directory structures for
    projects or ensuring required paths exist.
    
    Args:
        path: Directory path to create
        
    Returns:
        Dictionary with the result of the operation
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Normalize the path
            dir_path = os.path.abspath(path)

            # Validate path
            if not validate_path(dir_path, ALLOWED_DIRECTORIES):
                return {
                    "status": "error",
                    "message": f"Access denied: {path} is not within allowed directories"
                }

            # No need to check if parent directory exists - os.makedirs will create all needed parents
            # Just check if we have permission to write to the nearest existing parent directory
            current_path = dir_path
            while current_path and not os.path.exists(current_path):
                current_path = os.path.dirname(current_path)

            # If we found an existing parent, check if it's writable
            if current_path and not os.access(current_path, os.W_OK):
                return {
                    "status": "error",
                    "message": f"Permission denied: Cannot write to parent directory {current_path}"
                }

            # Create the directory (and any missing parent directories)
            try:
                os.makedirs(dir_path, exist_ok=True)
                logger.info(f"Successfully created directory: {dir_path}")

                # Check if directory exists after creation
                if os.path.exists(dir_path) and os.path.isdir(dir_path):
                    existed = os.path.exists(dir_path) and os.path.isdir(dir_path)
                    return {
                        "status": "success",
                        "message": f"Directory {'already exists' if existed else 'created successfully'}: {path}",
                        "path": path,
                        "already_existed": existed
                    }
                else:
                    return {
                        "status": "error",
                        "message": f"Failed to create directory: {path}"
                    }
            except Exception as e:
                logger.error(f"Error creating directory {dir_path}: {str(e)}")
                return {
                    "status": "error",
                    "message": f"Error creating directory: {str(e)}"
                }
        except Exception as e:
            logger.error(f"Error in create_directory: {str(e)}")
            return {
                "status": "error",
                "message": f"Error creating directory: {str(e)}"
            }

@mcp.tool()
def directory_tree(path: str, max_depth: int = 5) -> Dict[str, Any]:
    """
    Get a recursive tree view of files and directories as a JSON structure.
    
    This tool provides a hierarchical representation of a directory structure up to a specified
    maximum depth. Great for understanding project layouts or exploring directory contents.
    
    Args:
        path: The root directory path to visualize
        max_depth: Maximum depth of recursion (default: 5)
        
    Returns:
        Dictionary containing the hierarchical file and directory structure
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Normalize the path
            dir_path = os.path.abspath(path)

            # Validate path
            if not validate_path(dir_path, ALLOWED_DIRECTORIES):
                return {
                    "status": "error",
                    "message": f"Access denied: {path} is not within allowed directories"
                }

            # Check if directory exists
            if not os.path.exists(dir_path):
                return {
                    "status": "error",
                    "message": f"Directory not found: {path}"
                }

            # Check if path is a directory
            if not os.path.isdir(dir_path):
                return {
                    "status": "error",
                    "message": f"Not a directory: {path}"
                }

            # Check if we have read permission
            if not os.access(dir_path, os.R_OK):
                return {
                    "status": "error",
                    "message": f"Permission denied: Cannot read directory {path}"
                }

            # Function to recursively build the tree
            def build_tree(current_path, current_depth=0):
                """Build a recursive tree structure of the directory"""
                # Check if we've reached the maximum depth
                if current_depth > max_depth:
                    return {
                        "name": os.path.basename(current_path) or current_path,
                        "type": "directory",
                        "children": [{"name": "...", "type": "truncated"}]
                    }

                # Create the base node for this path
                name = os.path.basename(current_path) or current_path
                result = {
                    "name": name,
                    "type": "directory",
                    "children": []
                }

                try:
                    # Get all entries in the directory
                    entries = sorted(os.scandir(current_path), key=lambda e: (e.is_file(), e.name))

                    # Process each entry
                    for entry in entries:
                        # Skip hidden files and common excluded directories
                        if entry.name.startswith('.') or entry.name in ['__pycache__', 'node_modules', '.git', 'venv', 'env']:
                            continue

                        if entry.is_dir():
                            # Recursively process subdirectories
                            child = build_tree(entry.path, current_depth + 1)
                            result["children"].append(child)
                        else:
                            # Add files as leaf nodes
                            result["children"].append({
                                "name": entry.name,
                                "type": "file"
                            })
                except PermissionError:
                    result["error"] = "Permission denied"
                except Exception as e:
                    result["error"] = str(e)

                return result

            # Build the tree structure
            tree = build_tree(dir_path)

            # Return with success status and metadata
            return {
                "status": "success",
                "path": path,
                "max_depth": max_depth,
                "tree": tree,
                "message": f"Generated directory tree for {path} with max depth {max_depth}"
            }
        except Exception as e:
            logger.error(f"Error generating directory tree: {str(e)}")
            return {
                "status": "error",
                "message": f"Error generating directory tree: {str(e)}"
            }

@mcp.tool()
def get_file_info(path: str) -> Dict[str, Any]:
    """
    Retrieve detailed metadata about a file or directory.
    
    Returns comprehensive information including size, creation time, last modified time, 
    permissions, and type. This tool is perfect for understanding file characteristics 
    without reading the actual content.
    
    Args:
        path: Path to the file or directory
        
    Returns:
        Dictionary with detailed file/directory metadata
    """
    # Pause monitoring during this operation
    with MonitoringPauser():
        try:
            # Normalize the path
            file_path = os.path.abspath(path)

            # Validate path
            if not validate_path(file_path, ALLOWED_DIRECTORIES):
                return {
                    "status": "error",
                    "message": f"Access denied: {path} is not within allowed directories"
                }

            # Check if path exists
            if not os.path.exists(file_path):
                return {
                    "status": "error",
                    "message": f"Path not found: {path}"
                }

            # Check if we have read permission
            if not os.access(file_path, os.R_OK):
                return {
                    "status": "error",
                    "message": f"Permission denied: Cannot read {path}"
                }

            # Get basic file info
            is_dir = os.path.isdir(file_path)
            stat_info = os.stat(file_path)

            # Determine if it's a symlink
            is_symlink = os.path.islink(file_path)

            # Build the base info dictionary
            info = {
                "name": os.path.basename(file_path),
                "path": file_path,
                "type": "directory" if is_dir else "file",
                "is_symlink": is_symlink,
                "size": stat_info.st_size,
                "created": stat_info.st_ctime,
                "modified": stat_info.st_mtime,
                "accessed": stat_info.st_atime,
                "permissions": {
                    "read": os.access(file_path, os.R_OK),
                    "write": os.access(file_path, os.W_OK),
                    "execute": os.access(file_path, os.X_OK)
                }
            }

            # Add type-specific information
            if not is_dir:
                # File-specific information
                extension = os.path.splitext(file_path)[1].lstrip('.')
                mime_type, _ = mimetypes.guess_type(file_path)

                info.update({
                    "extension": extension or "(none)",
                    "mime_type": mime_type or "application/octet-stream"
                })

                # Try to determine if it's a text or binary file
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        # Read a small chunk to check if it's text
                        f.read(1024)
                    info["text_file"] = True
                except UnicodeDecodeError:
                    info["text_file"] = False
            else:
                # Directory-specific information
                try:
                    # Count files and subdirectories
                    entries = list(os.scandir(file_path))
                    files = [e for e in entries if e.is_file()]
                    dirs = [e for e in entries if e.is_dir()]

                    info["contents"] = {
                        "files": len(files),
                        "directories": len(dirs),
                        "total_entries": len(entries)
                    }

                    # List the first few entries (up to 10)
                    info["entries"] = [entry.name for entry in entries[:10]]
                    if len(entries) > 10:
                        info["entries"].append("... and more")
                except Exception as e:
                    info["error"] = f"Error reading directory contents: {str(e)}"

            # Add symlink information if applicable
            if is_symlink:
                try:
                    info["symlink_target"] = os.readlink(file_path)
                except:
                    info["symlink_target"] = "Could not read symlink target"

            return {
                "status": "success",
                "info": info
            }
        except Exception as e:
            logger.error(f"Error getting file info: {str(e)}")
            return {
                "status": "error",
                "message": f"Error getting file info: {str(e)}"
            }

@mcp.prompt()
def ai_librarian_help() -> str:
    """
    Provide help with AI Librarian functionality.
    """
    return """
    The AI Dev Toolkit helps me understand your codebase better. Here's how to use it:
    
    1. Initialize: `initialize_librarian("path/to/project")`
    2. Query a component: `query_component("path/to/project", "ComponentName")`
    3. Find implementations: `find_implementation("path/to/project", "search text")`
    4. Manage to-dos: `add_todo("path/to/project", "Task title")` and `list_todos("path/to/project")`
    5. Check code quality: `sanity_check("path/to/project")`
    
    File Operations:
    - Read files: `read_file("path/to/file")`
    - Read multiple files: `read_multiple_files(["path1", "path2"])`
    - Edit files: `edit_file("path/to/file", "old text", "new text")`
    - Write files: `write_file("path/to/file", "content")`
    - Move files: `move_file("source", "destination")`
    - Create directories: `create_directory("path/to/dir")`
    - Search files: `search_files("path", "pattern", excludePatterns=["node_modules"])`
    - Get file info: `get_file_info("path/to/file")`
    - View directory tree: `directory_tree("path/to/dir", max_depth=3)`
    
    Once initialized, I'll monitor your project for changes, providing:
    - Component tracking
    - Cross-file reference detection
    - To-do management across conversations
    - Code organization insights
    
    Would you like me to explain any specific feature in more detail?
    """

# Register TaskBoard tools if available
if TASKBOARD_AVAILABLE:
    print("Registering TaskBoard tools...")
    
    @mcp.tool()
    def think(thought: str) -> str:
        """
        Use this tool as a scratchpad to think about something without taking action.
        
        The think tool helps break down complex problems, verify requirements,
        check if plans comply with rules, and reflect on tool results. It doesn't
        modify any files or perform external actions.
        
        Example uses:
        - List specific rules that apply to the current request
        - Check if all required information is collected
        - Verify that planned actions comply with policies
        - Analyze tool results for correctness
        
        Args:
            thought: Your thought or reflection to process
            
        Returns:
            The formatted thought or reflection
        """
        try:
            print("Importing standalone think tool")
            from aitoolkit.librarian.think_tool import think as standalone_think
            print("Successfully imported standalone think tool")
            return standalone_think(thought)
        except ImportError as e:
            print(f"Error importing think_tool: {e}")
            # Fallback implementation if the module isn't available
            return f"<reflection>\n{thought}\n</reflection>"
    
    @mcp.tool()
    def submit_background_task(project_path: str, task_type: str, parameters: dict, priority: str = "medium") -> str:
        """
        Submit a task to be processed asynchronously
        
        Args:
            project_path: Path to the project
            task_type: Type of task (e.g., "code_analysis", "semantic_search")
            parameters: Parameters for the task
            priority: Priority of the task ("high", "medium", "low")
            
        Returns:
            Task ID
        """
        # Call the imported function from task_board.py, not recursively call this function
        from aitoolkit.librarian.task_board import submit_background_task as _submit_task
        return _submit_task(project_path, task_type, parameters, priority)
    
    @mcp.tool()
    def get_task_status(project_path: str, task_id: str) -> str:
        """
        Get the status of a background task
        
        Args:
            project_path: Path to the project
            task_id: ID of the task to check
            
        Returns:
            Task status
        """
        return get_task_status_mcp(project_path, task_id)
    
    @mcp.tool()
    def get_task_result(project_path: str, task_id: str) -> str:
        """
        Get the result of a completed background task
        
        Args:
            project_path: Path to the project
            task_id: ID of the task to get the result for
            
        Returns:
            Task result
        """
        return get_task_result_mcp(project_path, task_id)
    
    @mcp.tool()
    def cancel_task(project_path: str, task_id: str) -> str:
        """
        Cancel a pending background task
        
        Args:
            project_path: Path to the project
            task_id: ID of the task to cancel
            
        Returns:
            Result of the cancellation attempt
        """
        return cancel_task_mcp(project_path, task_id)
    
    @mcp.tool()
    def list_tasks(project_path: str, status: str = None, task_type: str = None) -> str:
        """
        List background tasks
        
        Args:
            project_path: Path to the project
            status: Optional status filter ("pending", "running", "completed", "failed", "timeout", "cancelled")
            task_type: Optional task type filter
            
        Returns:
            List of tasks
        """
        return list_tasks_mcp(project_path, status, task_type)
        
    @mcp.tool()
    def deep_analysis(project_path: str, query: str, priority: str = "high") -> str:
        """
        Start a deep analysis task that processes complex problems asynchronously
        
        Unlike the 'think' tool which provides immediate reflection,
        this function submits a background task for deeper analysis that
        may take some time to complete.
        
        Args:
            project_path: Path to the project
            query: The question or problem to analyze
            priority: Priority of the task ("high", "medium", "low")
            
        Returns:
            Task ID for the deep analysis task
        """
        try:
            print("Starting deep analysis task")
            from aitoolkit.librarian.task_board import task_deep_analysis
            print("Successfully imported task_deep_analysis")
            return task_deep_analysis(project_path, query, priority)
        except ImportError as e:
            print(f"Error importing task_deep_analysis: {e}")
            return f"Error: Could not import deep analysis function: {e}"

# Initialize TaskBoard if available
if TASKBOARD_AVAILABLE:
    try:
        # Apply TaskBoard integration to server context
        print("Initializing TaskBoard system...")
        # Verify task_deep_analysis is available
        print(f"TaskBoard tools available: {'task_deep_analysis' in globals()}")
        
        server_context = {
            "mcp_tools": globals(),
            "project_path": os.getcwd(),  # Will be updated when project paths are set
            "initialize_server": None  # Placeholder
        }
        
        # Make sure the think and taskboard tools are registered properly
        print("Re-registering TaskBoard tools with explicit paths...")
        from aitoolkit.librarian.task_board import (
            submit_background_task,
            get_task_status_mcp,
            get_task_result_mcp,
            cancel_task_mcp,
            list_tasks_mcp,
            task_deep_analysis
        )
        
        # Apply the standard TaskBoard integration
        apply_taskboard_integration(server_context)
        
        # Initialize Tool Reference TaskBoard integration
        try:
            from aitoolkit.librarian.tool_reference_taskboard import (
                register_tool_reference_task_type,
                initialize_tool_reference_async,
                update_tool_reference_async,
                cross_reference_async
            )
            
            # Register the tool reference task type
            register_tool_reference_task_type()
            
            # Add Tool Reference TaskBoard MCP tools
            @mcp.tool
            def tool_reference_initialize_async(project_path: str, priority: str = "medium") -> str:
                """
                Initialize the Tool Reference system asynchronously using TaskBoard.
                
                This tool creates the .tool_reference directory structure and builds a comprehensive
                metadata system that helps Claude select and use tools effectively. Since this
                operation can take time for large projects, it runs asynchronously through
                the TaskBoard system.
                
                Args:
                    project_path: The root directory of the project
                    priority: Task priority (high, medium, low)
                    
                Returns:
                    Task ID for tracking the operation
                """
                return initialize_tool_reference_async(project_path, priority)
            
            @mcp.tool
            def tool_reference_update_async(project_path: str, priority: str = "medium") -> str:
                """
                Update the Tool Reference system asynchronously using TaskBoard.
                
                This tool updates an existing Tool Reference with the latest tool metadata.
                Since this operation can take time for large projects, it runs asynchronously
                through the TaskBoard system.
                
                Args:
                    project_path: The root directory of the project
                    priority: Task priority (high, medium, low)
                    
                Returns:
                    Task ID for tracking the operation
                """
                return update_tool_reference_async(project_path, priority)
            
            @mcp.tool
            def tool_reference_cross_reference(project_path: str, priority: str = "medium") -> str:
                """
                Create cross-references between .ai_reference and .tool_reference asynchronously.
                
                This tool establishes bidirectional links between the AI Librarian context
                and the Tool Reference system, improving Claude's ability to navigate between
                code components and the tools that operate on them.
                
                Args:
                    project_path: The root directory of the project
                    priority: Task priority (high, medium, low)
                    
                Returns:
                    Task ID for tracking the operation
                """
                return cross_reference_async(project_path, priority)
                
            print("Tool Reference TaskBoard integration initialized successfully")
        except Exception as e:
            print(f"Error initializing Tool Reference TaskBoard integration: {e}")
        
        print("TaskBoard system initialized successfully")
    except Exception as e:
        print(f"Error initializing TaskBoard: {e}")

# Register git tracking tools

@mcp.tool()
def get_git_info(project_path: str, refresh: bool = False) -> Dict[str, Any]:
    """
    Get information about the git repository for a project.
    
    This tool provides comprehensive git information including repository status,
    commit history, branches, tags, and remotes. It uses a cache to improve performance
    for repeated calls.
    
    Args:
        project_path: Path to the project directory
        refresh: Force refresh the git information cache
        
    Returns:
        Dictionary containing git repository information
    """
    with state_lock:
        # Check if we have cached git info and it's recent enough (5 minutes)
        current_time = time.time()
        cache_entry = librarian_context["git_info"].get(project_path)
        
        if not refresh and cache_entry and (current_time - cache_entry.get("timestamp", 0) < 300):
            return {
                "status": "success",
                "message": "Retrieved git information from cache",
                "data": cache_entry["data"],
                "from_cache": True
            }
    
    try:
        # Gather git information
        status = get_repository_status(repo_path=project_path)
        commits = get_commit_history(num_commits=30, repo_path=project_path)
        branches = get_branches(repo_path=project_path)
        tags = get_tags(repo_path=project_path)
        remotes = get_remotes(repo_path=project_path)
        
        # Combine the information
        git_info = {
            "status": status,
            "commits": commits,
            "branches": branches,
            "tags": tags,
            "remotes": remotes,
            "last_updated": datetime.datetime.now().isoformat()
        }
        
        # Cache the information
        with state_lock:
            librarian_context["git_info"][project_path] = {
                "timestamp": time.time(),
                "data": git_info
            }
        
        return {
            "status": "success",
            "message": "Git information retrieved successfully",
            "data": git_info,
            "from_cache": False
        }
    except Exception as e:
        logger.error(f"Error getting git information: {str(e)}")
        return {
            "status": "error",
            "message": f"Error getting git information: {str(e)}",
            "error": str(e)
        }

@mcp.tool()
def update_git_history(project_path: str, history_dir: str = None) -> Dict[str, Any]:
    """
    Update git history files for a project.
    
    This tool creates or updates the git history files in a specified directory.
    These files can be used by Claude to understand the repository history.
    
    Args:
        project_path: Path to the project directory
        history_dir: Directory where to store history files (default: .git_history in project_path)
        
    Returns:
        Dictionary with results of the operation
    """
    try:
        result = update_git_history_files(repo_path=project_path, history_dir=history_dir)
        
        # Update the git info cache
        if result["status"] == "success":
            with state_lock:
                # Force refresh git info on next call
                if project_path in librarian_context["git_info"]:
                    del librarian_context["git_info"][project_path]
        
        return result
    except Exception as e:
        logger.error(f"Error updating git history files: {str(e)}")
        return {
            "status": "error",
            "message": f"Error updating git history files: {str(e)}",
            "error": str(e)
        }

# Register Security Analyzer tools if available - only registers, doesn't analyze anything yet
if SECURITY_ANALYZER_AVAILABLE:
    try:
        # Just register the tools, don't do any analysis at startup
        print("Registering Security Analyzer tools...")
        if 'server_context' not in locals():
            server_context = {
                "mcp_tools": globals(),
                "project_path": os.getcwd(),  # Will be updated when project paths are set
                "initialize_server": None  # Placeholder
            }
        
        # Add mcp to server context
        server_context["mcp"] = mcp
        
        # Add the original sanity_check function to context for enhancement
        for key, value in globals().items():
            if key == "sanity_check":
                server_context[key] = value
                break
        
        # Just register the tools, don't perform any analysis yet
        apply_security_analyzer_integration(server_context)
        print("Security Analyzer tools registered successfully")
    except Exception as e:
        print(f"Error registering Security Analyzer tools: {e}")

# Register MCP Extensions (prompts and resources)
if MCP_EXTENSIONS_AVAILABLE:
    print("Registering MCP Extensions (prompts and resources)...")
    try:
        register_mcp_extensions(mcp)
        print("MCP Extensions registered successfully")
    except Exception as e:
        print(f"Error registering MCP Extensions: {e}")

# Register Prompt Tools
if PROMPT_TOOLS_AVAILABLE:
    print("Registering Prompt Tools...")
    try:
        register_prompt_like_tools(mcp)
        print("Prompt Tools registered successfully")
    except Exception as e:
        print(f"Error registering Prompt Tools: {e}")

@mcp.tool()
def server_ready() -> Dict[str, Any]:
    """
    Called by Claude Desktop to indicate the server is ready.
    This starts background processes after initialization.
    """
    try:
        start_monitoring()
        start_heartbeat()
        return {
            "status": "ready",
            "monitoring": "started",
            "message": "AI Librarian server is fully initialized"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "message": "Failed to start monitoring"
        }

# Heartbeat mechanism to prevent timeouts
heartbeat_active = False
heartbeat_thread = None

def start_heartbeat():
    """Start the heartbeat thread to prevent connection timeouts."""
    global heartbeat_active, heartbeat_thread
    if not heartbeat_active:
        heartbeat_active = True
        heartbeat_thread = threading.Thread(target=heartbeat_worker, daemon=True)
        heartbeat_thread.start()
        logger.info("Started heartbeat thread")

def heartbeat_worker():
    """Send periodic heartbeat signals to prevent timeouts."""
    while heartbeat_active:
        try:
            # Send a minimal signal to keep connection alive
            logger.debug("Heartbeat signal")
            time.sleep(5)  # Every 5 seconds
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
            time.sleep(10)

@mcp.tool()
def heartbeat() -> Dict[str, str]:
    """Simple heartbeat endpoint for connection monitoring."""
    return {"status": "alive", "timestamp": time.time()}

if __name__ == "__main__":
    # Initialize any directories passed as command-line arguments
    # This will also initialize the TaskBoard for these directories
    
    # Add a delayed start for monitoring to prevent initialization timeout
    def delayed_monitoring_start():
        time.sleep(5)  # Wait 5 seconds after server starts
        if not monitoring_started:
            logger.info("Auto-starting monitoring after delay")
            start_monitoring()
        if not heartbeat_active:
            logger.info("Auto-starting heartbeat after delay")
            start_heartbeat()
    
    # Start monitoring in a separate thread after a delay
    delay_thread = threading.Thread(target=delayed_monitoring_start, daemon=True)
    delay_thread.start()
    
    mcp.run()
