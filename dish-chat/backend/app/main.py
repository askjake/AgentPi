import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.cors_middleware import LocalNetworkCORSMiddleware
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row
from langgraph.checkpoint.memory import MemorySaver

from app.config import get_settings
from app.db import sessionmanager
from app.agent.checkpoint import EncryptedAsyncPostgresSaver
from app.agent.agents.tools.registry import initialize_mcp_tools
from app.agent.db_utils import checkpointer
from app.background_mgr.service import get_task_manager
from app.analytics.idle_chat_checker import start_idle_chat_checker, stop_idle_chat_checker
from app.middlewares import LocalIdInjectMiddleware, LogRespMiddleware
from app.logs.router import router as logs_router
from app.analytics.router import router as analytics_router
from app.logassist.router import router as logassist_router
from app.analytics.web_searches import router as web_searches_router
from app.agent_mode.runs_router import router as runs_router
from app.agent_mode.artifacts_router import router as artifacts_router

settings = get_settings()

logging.basicConfig(
    stream=sys.stdout,
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s,%(msecs)03d %(levelname)s %(pathname)s:%(lineno)d:%(funcName)s() %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
logger.debug(
    "Settings loaded: name=%s version=%s local=%s pll_provider=%s ell_provider=%s",
    settings.NAME,
    settings.VERSION,
    settings.LOCAL,
    settings.PLLM_PROVIDER,
    settings.ELLM_PROVIDER,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    async_conn_pool = None
    await initialize_mcp_tools()
    app.include_router(logassist_router, prefix=settings.API_PREFIX)
    app.include_router(logs_router, prefix=settings.API_PREFIX)
    app.include_router(analytics_router, prefix=settings.API_PREFIX)
    try:
        if sys.platform == "win32":
            checkpointer["checkpointer"] = MemorySaver()
            logger.warning(
                "Windows: using in-memory LangGraph checkpointer; "
                "application data remains in PostgreSQL"
            )
        else:
            # Set up Langgraph checkpointer with it's own async conn pool
            async_conn_pool = AsyncConnectionPool(
                conninfo=settings.POSTGRES_URL,
                max_lifetime=600,  # 10 minutes
                max_idle=300,  # Close idle connections after 5 minute
                min_size=5,
                max_size=100,
                timeout=30,
                open=False,
                check=AsyncConnectionPool.check_connection,
                kwargs={
                    "autocommit": True,
                    "row_factory": dict_row,
                },
            )
            await async_conn_pool.open()
            if async_conn_pool.closed:
                logger.error(f"psycopg connection to POSTGRES failed.")
                raise RuntimeError("Failed to connect to PostgreSQL")

            await initialize_mcp_tools()
            checkpointer["checkpointer"] = EncryptedAsyncPostgresSaver(async_conn_pool)
            await checkpointer["checkpointer"].setup()

        # Start idle chat checker if enabled
        if settings.IDLE_CHAT_CHECKER_ENABLED:
            start_idle_chat_checker(
                check_interval_minutes=settings.IDLE_CHAT_CHECK_INTERVAL_MINUTES,
                idle_threshold_minutes=settings.IDLE_CHAT_THRESHOLD_MINUTES,
                min_messages=settings.IDLE_CHAT_MIN_MESSAGES
            )
            logger.info("Started idle chat checker")


        yield

    except Exception as e:
        logging.error(f"Error in lifespan: {type(e).__name__} - {e}")
        raise
    finally:
        # Cleanup in reverse order
        # Stop idle chat checker
        if settings.IDLE_CHAT_CHECKER_ENABLED:
            await stop_idle_chat_checker(timeout=5)
        await get_task_manager().shutdown(max_wait_time=settings.CLEANUP_TIMEOUT)
        await sessionmanager.close()
        if async_conn_pool and not async_conn_pool.closed:
            await async_conn_pool.close()


app = FastAPI(
    lifespan=lifespan,
    title=settings.NAME,
    docs_url="/api/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Always enable CORS for configured origins
# CORS configuration - Allow all origins
# CORS: Allow all 10.*.*.* network origins dynamically
app.add_middleware(LocalNetworkCORSMiddleware)

# Local development middleware
if settings.LOCAL:
    app.add_middleware(LocalIdInjectMiddleware)

if settings.DEBUG:
    app.add_middleware(LogRespMiddleware)


from app.health.router import router as health_router
from app.user.router import router as user_router
from app.chat.router import router as chat_router
from app.message.router import router as message_router
from app.attachment.router import router as attachment_router
from app.vault.router import router as vault_router
from app.usage_tracking.router import router as usage_tracking_router
from app.releases.router import router as releases_router
from app.chat_group.router import router as chat_group_router
from app.agent.routers import router as agent_router
from app.journal.router import router as journal_router
from app.settings_router import router as settings_router






app.include_router(health_router, prefix=settings.API_PREFIX)
app.include_router(user_router, prefix=settings.API_PREFIX)
app.include_router(chat_router, prefix=settings.API_PREFIX)
app.include_router(message_router, prefix=settings.API_PREFIX)
app.include_router(attachment_router, prefix=settings.API_PREFIX)
app.include_router(vault_router, prefix=settings.API_PREFIX)
app.include_router(usage_tracking_router, prefix=settings.API_PREFIX)
app.include_router(releases_router, prefix=settings.API_PREFIX)
app.include_router(chat_group_router, prefix=settings.API_PREFIX)
app.include_router(agent_router, prefix=settings.API_PREFIX)
app.include_router(
    journal_router,
    prefix=settings.API_PREFIX,
    tags=["journal"]
)

# Log Assist routes
app.include_router(
    logassist_router,
    prefix=f"{settings.API_PREFIX}/logassist",
    tags=["logassist"],
)


# Web search analytics (used by ChatToolsPanel "Web search" tab)
app.include_router(
    web_searches_router,
    prefix=f"{settings.API_PREFIX}/analytics",
    tags=["analytics"],
)

# Agent-mode runs (used by ChatToolsPanel "Automation runs" tab)
app.include_router(
    runs_router,
    prefix=f"{settings.API_PREFIX}/agent-mode",
    tags=["agent-mode"],
)

# Agent-mode artifacts (used for downloading generated files)
app.include_router(
    artifacts_router,
    prefix=f"{settings.API_PREFIX}/agent-mode",
    tags=["agent-mode"],
)

# Thought Visualization endpoint (for debugging extended thinking)
try:
    from app.viz_router import router as viz_router
    app.include_router(
        viz_router,
        prefix=f"{settings.API_PREFIX}/viz",
        tags=["visualization"],
    )
    logger.info("Thought Visualizer router registered at /viz")
except ImportError as e:
    logger.warning(f"Thought Visualizer not available: {e}")

# LLM Configuration Router - Multi-provider LLM support
from app.llm_config.router import router as llm_config_router
app.include_router(
    llm_config_router,
    prefix=f"{settings.API_PREFIX}/llm",
    tags=["llm-config"]
)

if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.FASTAPI_HOST, port=settings.FASTAPI_PORT)
