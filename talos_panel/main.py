from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from talos_panel.api import router as servers_router
from talos_panel.auth import AuthenticationMiddleware
from talos_panel.auth_api import router as auth_api_router
from talos_panel.auth_web import router as auth_web_router
from talos_panel.bootstrap import ensure_secret
from talos_panel.config import get_settings
from talos_panel.db import SessionFactory
from talos_panel.install_service import InstallationManager
from talos_panel.runtime import DockerRuntime
from talos_panel.schemas import Health
from talos_panel.web import router as web_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.secret_key = ensure_secret(settings.secret_file)
    app.state.runtime = DockerRuntime(settings)
    app.state.installation_manager = InstallationManager(settings, SessionFactory)
    await app.state.installation_manager.start()
    try:
        yield
    finally:
        await app.state.installation_manager.stop()


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(AuthenticationMiddleware, settings=settings)
app.include_router(servers_router, prefix=settings.api_prefix)
app.include_router(auth_api_router, prefix=settings.api_prefix)
app.mount("/static", StaticFiles(directory="talos_panel/static"), name="static")
app.include_router(auth_web_router)
app.include_router(web_router)


@app.get("/health", response_model=Health, tags=["system"])
async def health() -> Health:
    return Health()
