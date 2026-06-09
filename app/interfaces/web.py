"""
KazmaAI Web Interface

Provides:
- FastAPI web server
- HTMX-powered real-time updates
- RTL support for Arabic
- Chat, Project, and Create workspaces
"""

import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from fastapi import FastAPI, Request, Form, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import KazmaAI


def create_web_app(agent: KazmaAI, config: Dict[str, Any]) -> FastAPI:
    """
    Create FastAPI web application for KazmaAI.
    
    Args:
        agent: KazmaAI agent instance
        config: Web configuration from config.yaml
        
    Returns:
        FastAPI application
    """
    app = FastAPI(title="KazmaAI", description="Cross-platform AI Agent")
    
    # Setup templates and static files
    base_path = Path(__file__).parent
    templates_path = base_path / "web" / "templates"
    static_path = base_path / "web" / "static"
    
    # Create directories if they don't exist
    templates_path.mkdir(parents=True, exist_ok=True)
    static_path.mkdir(parents=True, exist_ok=True)
    
    templates = Jinja2Templates(directory=str(templates_path))
    
    # Mount static files
    if static_path.exists():
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
    
    # Store agent reference
    app.state.agent = agent
    app.state.templates = templates
    
    # =========================================================================
    # ROUTES
    # =========================================================================
    
    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        """Home page - redirect to chat."""
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/chat")
    
    @app.get("/chat", response_class=HTMLResponse)
    async def chat_page(request: Request):
        """Chat workspace."""
        return templates.TemplateResponse(
            "chat.html",
            {
                "request": request,
                "title": "Chat / دردشة",
                "rtl_enabled": True,
                "language": "ar",
            },
        )
    
    @app.get("/projects", response_class=HTMLResponse)
    async def projects_page(request: Request):
        """Projects workspace."""
        workspace = agent.workspace
        projects = workspace.list_projects()
        
        return templates.TemplateResponse(
            "projects.html",
            {
                "request": request,
                "title": "Projects / المشاريع",
                "projects": projects,
                "rtl_enabled": True,
                "language": "ar",
            },
        )
    
    @app.post("/api/chat")
    async def api_chat(message: str = Form(...), conversation_id: str = "web"):
        """Chat API endpoint."""
        response = await agent.chat(message, conversation_id)
        return {"response": response, "timestamp": datetime.utcnow().isoformat()}
    
    @app.post("/api/projects/create")
    async def api_create_project(name: str = Form(...), description: str = Form("")):
        """Create project API endpoint."""
        result = agent.create_project(name, description)
        return {"success": True, "message": result}
    
    @app.get("/api/projects")
    async def api_list_projects():
        """List projects API endpoint."""
        projects = agent.workspace.list_projects()
        return {
            "projects": [
                {
                    "id": p.project_id,
                    "name": p.name,
                    "description": p.description,
                    "status": p.status,
                    "tasks": len(p.tasks),
                }
                for p in projects
            ]
        }
    
    @app.get("/api/status")
    async def api_status():
        """Agent status API endpoint."""
        return {
            "status": "running",
            "projects": agent.workspace.get_stats(),
            "memory": agent.memory.get_stats(),
            "events": agent.event_bus.get_stats(),
        }
    
    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
    
    return app


async def run_web_server(agent: KazmaAI, config: Dict[str, Any]):
    """
    Run web server as part of KazmaAI.
    
    Args:
        agent: KazmaAI agent instance
        config: Web configuration from config.yaml
    """
    if not config.get('enabled', False):
        return
    
    import uvicorn
    
    host = config.get('host', '127.0.0.1')
    port = config.get('port', 8080)
    
    app = create_web_app(agent, config)
    
    print(f"\n🌐 Web interface running at: http://{host}:{port}")
    print(f"   Chat: http://{host}:{port}/chat")
    print(f"   Projects: http://{host}:{port}/projects")
    
    config_uvicom = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
    )
    
    server = uvicorn.Server(config_uvicom)
    await server.serve()