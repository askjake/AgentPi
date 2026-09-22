import copy
from typing import Literal, Optional, ClassVar
from functools import lru_cache, cached_property
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import computed_field


@lru_cache
def get_settings():
    settings = Settings()
    if settings.BETAREPORT_MCP_TOKEN:
        beta_config = copy.deepcopy(settings.BETAREPORT_MCP_CONFIG)
        beta_config.setdefault("beta_report", {}).setdefault("headers", {})[
            "Authorization"
        ] = f"Bearer {settings.BETAREPORT_MCP_TOKEN}"
        settings.BETAREPORT_MCP_CONFIG = beta_config
    return settings


class Settings(BaseSettings):
    NAME: str = "Dish-Chat"
    VERSION: str = "2.1.0"
    API_PREFIX: str = "/rest/api/v1"

    # Runtime settings
    DEBUG: bool = False
    LOCAL: bool = True

    # ============================================================================
    # AUTHENTICATION SETTINGS - ATLASSIAN SSO INTEGRATION
    # ============================================================================
    # Production: oauth2-proxy injects X-Auth-Request-Email header with user's
    # Atlassian email (e.g., user@dish.com). This ties to Jira/Confluence access.
    # Development: Set AUTH_DISABLED=True to bypass and use DEFAULT_USER_EMAIL
    # Network: 10.*.*.* networks are allowed via CORS and oauth2-proxy config
    # ============================================================================
    AUTH_DISABLED: bool = False  # Set to True ONLY for local dev/testing
    DEFAULT_USER_EMAIL: str = "jacob.montgomery@dish.com"  # Fallback for local dev

    # VERIFIED: oauth2-proxy handles Atlassian SSO and injects email header
    # The user's email from Atlassian is used for:
    # - Confluence API calls (CONFLUENCE_USER_EMAIL can be set per-user)
    # - Jira API calls (JIRA_USER_EMAIL can be set per-user)
    # - GitLab access (if user has GitLab account with same email)
    # ============================================================================

    ECHO_SQL: bool = False
    FASTAPI_HOST: str = "0.0.0.0"  # Listen on all interfaces
    FASTAPI_PORT: int = 8000
    CLEANUP_TIMEOUT: int = 600

    # Idle chat checker settings
    IDLE_CHAT_CHECKER_ENABLED: bool = True
    IDLE_CHAT_CHECK_INTERVAL_MINUTES: int = 10
    IDLE_CHAT_THRESHOLD_MINUTES: int = 30
    IDLE_CHAT_MIN_MESSAGES: int = 5
    SPOOLED_MAX_SIZE: int = 2 * 1024 * 1024
    # Default key is for testing only. Prod key is passed in via env var
    MASTER_KEY: str = "SoWTrLlo3xu1ExZIvSNQMpldDmUHc5cxbmrxlPN2RvI="

    # DB
    POSTGRES_HOST: str = "127.0.0.1"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "dishchat"
    POSTGRES_USER: str = "dev_user"
    POSTGRES_PWD: str = "dev123"

    @computed_field
    @cached_property
    def POSTGRES_URL(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PWD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @computed_field
    @cached_property
    def POSTGRES_SQLALCHEMY_URL(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PWD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # LLM Models - P for Power and E for Efficient
    PLLM_PROVIDER: Literal["aws-bedrock", "openai", "anthropic", "coverity-assist"] = "coverity-assist"
    PLLM_API_BASE: Optional[str] = None
    PLLM_MODEL: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"  # Reverted from 4.6 - requires inference profile
    PLLM_CTX_LEN: int = 200_000
    ELLM_PROVIDER: Optional[Literal["aws-bedrock", "openai", "anthropic", "coverity-assist"]] = "coverity-assist"
    ELLM_API_BASE: Optional[str] = None
    ELLM_MODEL: Optional[str] = "us.anthropic.claude-3-5-haiku-20241022-v1:0"
    ELLM_CTX_LEN: Optional[int] = 200_000
    LLM_TOKENIZER: Optional[str] = None
    DEFAULT_TEMP: float = 0.6
    DEFAULT_REASONING: bool = False
    
    # Coverity Assist Configuration - Tool Support Enabled
    COVERITY_ASSIST_URL: str = "https://coverity-assist-stg.dishtv.technology/chat"
    COVERITY_ASSIST_TOKEN: str = ""
    COVERITY_ASSIST_INFERENCE_PROFILE_ARN: Optional[str] = None
    COVERITY_ASSIST_VERIFY_SSL: bool = False
    COVERITY_ASSIST_TOP_LEVEL_SYSTEM: bool = True
    # Tool call support
    ENABLE_TOOL_CALLS: bool = True
    MAX_TOOL_ITERATIONS: int = 5
    TOOL_CALL_TIMEOUT: int = 300
    DEFAULT_MODEL_PREFERENCE: str = "reasoning"
    ollama_base_url: str = "http://localhost:11434"  # Ollama local LLM server
    REASONING_BUDGET: int = 6000

    # Embeddings
    EMBED_PROVIDER: Literal["aws-bedrock", "openai"] = "aws-bedrock"
    EMBED_API_BASE: Optional[str] = None
    EMBED_MODEL: str = "cohere.embed-multilingual-v3"
    EMBED_TOKENIZER: str = "Cohere/Cohere-embed-multilingual-v3.0"
    EMBED_CHUNK_SIZE: int = 300
    EMBED_OVERLAP: int = 5
    EMBED_BATCH_SIZE: int = 96
    SUMMARY_LEN: int = 300

    # AWS Settings
    AWS_REGION: Optional[str] = "us-west-2"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_ENDPOINT_URL: Optional[str] = None  # For MinIO/LocalStack
    AWS_FILESTORE_BUCKET: str = "dish-chat-filestore"
    
    # Agent uploads directory (alternative to S3 for log files)
    AGENT_UPLOADS_DIR: str = "/tmp/dish_chat_agent_uploads"

    # AWS Bedrock Configuration
    BEDROCK_READ_TIMEOUT: int = 900  # Increased to 15 min for complex tasks
    BEDROCK_CONNECT_TIMEOUT: int = 10
    BEDROCK_MAX_RETRIES: int = 5  # Increased for better resilience

    # Chat Settings
    MAX_CHAT_COUNT: int = 9999
    MAX_GROUPS_WITH_CHATS_COUNT: int = 20
    MAX_TITLE_LEN: int = 40
    MAX_TITLE_RETRY: int = 5

    # Message Settings
    MAX_VERSION_COUNT: int = 20
    MAX_IN_CTX_DOC_LEN: int = 200_000
    MAX_OUTPUT_COUNT: int = 64_000

    JOURNAL_MAX_MESSAGES: int = 1000  # Limit messages in journal

    # Attachment Settings
    SUPPORTED_DOC_TYPES: list[str] = [
        "application/pdf",
        "text/plain",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    SUPPORTED_LOG_TYPES: list[str] = [
        "text/plain",  # .log files
        "text/x-log",
        "application/x-log",
        "application/zip",  # .zip archives
        "application/gzip",  # .gz files
        "application/x-gzip",
        "application/x-tar",  # .tar files
        "application/x-compressed-tar",  # .tar.gz, .tgz
        "application/octet-stream",  # Generic binary (numbered logs)
    ]
    SUPPORTED_IMAGE_TYPES: list[str] = [
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
    ]
    MAX_IMAGE_RES: int = 1092 * 1092

    # Vault Settings
    VAULT_SESSION_DURATION_SEC: int = 3 * 3600
    ARGON2_TIME: int = 3
    ARGON2_MEM: int = 2 ** 16
    ARGON2_PRL: int = 1

    # Context Manager
    MAX_CONTEXT: int = 12000
    MAX_CONV_CACHE: float = 0.6
    SUMMARIZE_WORD_LIMIT: int = 500
    CACHE_EVICT_PROP: float = 0.5

    # Agent Settings
    MAX_CACHEPOINT_CNT: int = 4
    LANGGRAPH_RECURSION_LIMIT: int = 200

    # ============================================================================
    # MCP SERVER CONFIGURATIONS
    # ============================================================================

    # -------------------------------------------------------------------------
    # BETA REPORT MCP - VERIFIED ✅
    # -------------------------------------------------------------------------
    # Status: ACTIVE (HTTP 401 - requires auth token)
    # Function: ds-betareport-mcp-lambda
    # URL: https://7quifnvo576d2m5rhbnguwgvfq0qbivs.lambda-url.us-west-2.on.aws/
    # Auth: Bearer token from BETAREPORT_MCP_TOKEN
    # CORS: Configured for all origins (*)
    # InvokeMode: RESPONSE_STREAM
    # Purpose: Beta report analysis and querying
    # Network: Accessible from 10.*.*.* via Lambda Function URL
    # -------------------------------------------------------------------------
    BETAREPORT_MCP_TOKEN: str = ""

    BETAREPORT_MCP_CONFIG: dict = {
        "beta_report": {
            "transport": "streamable_http",
            "url": "https://7quifnvo576d2m5rhbnguwgvfq0qbivs.lambda-url.us-west-2.on.aws/mcp",
            "headers": {},
        }
    }

    # -------------------------------------------------------------------------
    # VIEWERSHIP MEASUREMENT MCP - VERIFIED ✅ (FIXED)
    # -------------------------------------------------------------------------
    # Status: ACTIVE (HTTP 200 - public access enabled)
    # Function: viewership-mcp
    # URL: https://h3exlf3obezoorw2wjcovzh4y40slpan.lambda-url.us-west-2.on.aws/
    # Auth: NONE (resource policy allows public invoke)
    # InvokeMode: RESPONSE_STREAM
    # Purpose: Viewership data analysis via Trino/Glue
    # Network: Accessible from 10.*.*.* via Lambda Function URL
    # IAM: Resource policy added for public invocation
    # FIXED: Corrected URL from oorw2wjcovzh4y40slpan -> h3exlf3obezoorw2wjcovzh4y40slpan
    # NOTE: Lambda has runtime error (exec format error) - needs Lambda fix
    # -------------------------------------------------------------------------
    VIEWERSHIP_MEASUREMENT_MCP_CONFIG: dict = {
        "viewership_measurement": {
            "transport": "streamable_http",
            "url": "https://cy4h556zxlhqyjju5psohdr6ou0scrxj.lambda-url.us-west-2.on.aws/mcp",
            "headers": {
                "Accept": "application/json, text/event-stream"
            }
        }
    }

    # -------------------------------------------------------------------------
    # LOG ASSIST MCP - LOCAL DEVELOPMENT ONLY ⚠
    # -------------------------------------------------------------------------
    # Status: LOCAL DEV ONLY (not deployed)
    # URL: http://127.0.0.1:5000/mcp
    # Purpose: Coverity assist / log analysis
    # Network: Localhost only - not accessible from 10.*.*.* networks
    # TODO: Deploy to Lambda or internal service for production use
    # -------------------------------------------------------------------------
    LOG_ASSIST_MCP_CONFIG: dict = {
        "log_assist": {
            "transport": "streamable_http",
            "url": "http://127.0.0.1:5000/mcp",
        }
    }

    # -------------------------------------------------------------------------
    # INTERNAL TOOLS MCP - PLACEHOLDER ⚠
    # -------------------------------------------------------------------------
    # Status: NOT CONFIGURED (placeholder domain)
    # Purpose: SSO-protected internal micro-tools
    # Network: Should be accessible from 10.*.*.* when deployed
    # TODO: Replace with actual internal service endpoint
    # Recommendation: Deploy as Lambda Function URL with IAM auth or
    #                 as Kubernetes service with oauth2-proxy protection
    # -------------------------------------------------------------------------
    INTERNAL_TOOLS_MCP_CONFIG: dict = {
        "internal_tools": {
            "transport": "streamable_http",
            "url": "https://internal-tools.yourdomain/mcp",  # PLACEHOLDER - NEEDS REPLACEMENT
        }
    }

    # ============================================================================
    # EXTERNAL SERVICE ENDPOINTS
    # ============================================================================

    # -------------------------------------------------------------------------
    # COVERITY GATEWAY - LOCAL DEVELOPMENT ONLY ⚠
    # -------------------------------------------------------------------------
    # Status: LOCAL DEV ONLY
    # Network: Localhost only
    # TODO: Deploy to production endpoint
    # -------------------------------------------------------------------------
    COVERITY_GATEWAY_URL: str = "http://127.0.0.1:5000"

    # -------------------------------------------------------------------------
    # SENTRY INTEGRATION - VERIFIED ✅
    # -------------------------------------------------------------------------
    # Status: ACTIVE
    # URL: https://ds-testing-sentry.dishtv.technology
    # Ingress: k8s-sentry-sentry-ee9d6ee130-1035253762.us-west-2.elb.amazonaws.com
    # Purpose: Cluster inspection and monitoring
    # Network: Accessible from 10.*.*.* via ingress
    # Auth: Requires SENTRY_AUTH_TOKEN (set via env var)
    # -------------------------------------------------------------------------
    SENTRY_AUTH_TOKEN: Optional[str] = None  # Set via environment variable
    SENTRY_ORG: str = "dishtv.technology"
    SENTRY_URL: str = "https://ds-testing-sentry.dishtv.technology"  # VERIFIED ✅
    SENTRY_PROJECT: Optional[str] = None

    # -------------------------------------------------------------------------
    # INTERNAL SEARCH - PLACEHOLDER ⚠
    # -------------------------------------------------------------------------
    # Status: NOT CONFIGURED (placeholder domain)
    # Purpose: Multi-source search (Confluence, GitLab, Jira)
    # Network: Should be accessible from 10.*.*.* when deployed
    # TODO: Replace with actual internal search service endpoint
    # -------------------------------------------------------------------------
    INTERNAL_SEARCH_URL: str = "https://internal-search.yourdomain/api/search"  # PLACEHOLDER
    INTERNAL_SEARCH_MODE: str = "multi"
    INTERNAL_SEARCH_TIMEOUT: float = 10.0
    INTERNAL_SEARCH_SOURCES: str = "confluence,gitlab,jira"

    # ============================================================================
    # DISH INTERNAL TOOLS - PLACEHOLDER ⚠
    # ============================================================================
    # Status: NOT CONFIGURED (placeholder domains)
    # Purpose: CART, CCTools, Portal access
    # Network: Should be accessible from 10.*.*.* corporate network
    # Auth: Likely requires VPN or internal network access
    # TODO: Verify actual hostnames and accessibility
    # ============================================================================
    CART_HOST: Optional[str] = "cart.dtc.dish.corp"  # NEEDS VERIFICATION
    CCTOOLS_HOST: Optional[str] = "cctools.dtc.dish.corp"  # NEEDS VERIFICATION
    PORTAL_HOST: Optional[str] = "inlpecca01.dtc.dish.corp"  # NEEDS VERIFICATION
    INTERNAL_TOOLS_TIMEOUT: float = 30.0

    # ============================================================================
    # ATLASSIAN INTEGRATION - VERIFIED ✅
    # ============================================================================
    # All Atlassian services use user's SSO email for authentication
    # The email from X-Auth-Request-Email header is used for API calls
    # API tokens should be set per-user or via service account
    # ============================================================================

    # -------------------------------------------------------------------------
    # CONFLUENCE - VERIFIED ✅
    # -------------------------------------------------------------------------
    # Status: ACTIVE
    # URL: https://dishtech-dishtv.atlassian.net/wiki
    # Auth: User email + API token (set via env var or per-user)
    # Network: Public Atlassian Cloud (accessible from anywhere)
    # User Binding: Uses X-Auth-Request-Email from oauth2-proxy
    # -------------------------------------------------------------------------
    CONFLUENCE_BASE_URL: str = "https://dishtech-dishtv.atlassian.net/wiki"  # VERIFIED ✅
    CONFLUENCE_USER_EMAIL: Optional[str] = None  # Auto-populated from SSO email
    CONFLUENCE_API_TOKEN: Optional[str] = None  # Set via environment variable

    # -------------------------------------------------------------------------
    # GITLAB - VERIFIED ✅
    # -------------------------------------------------------------------------
    # Status: ACTIVE
    # URL: https://gitlab.com (public GitLab)
    # Auth: Personal access token (set via env var)
    # Network: Public (accessible from anywhere)
    # User Binding: Token-based (not tied to SSO email directly)
    # -------------------------------------------------------------------------
    GITLAB_BASE_URL: str = "https://gitlab.com"  # VERIFIED ✅
    GITLAB_TOKEN: Optional[str] = None  # Set via environment variable
    GITLAB_SEARCH_SCOPES: str = "projects,blobs"

    # -------------------------------------------------------------------------
    # JIRA - VERIFIED ✅
    # -------------------------------------------------------------------------
    # Status: ACTIVE
    # URL: https://dishtech-dishtv.atlassian.net
    # Auth: User email + API token (set via env var or per-user)
    # Network: Public Atlassian Cloud (accessible from anywhere)
    # User Binding: Uses X-Auth-Request-Email from oauth2-proxy
    # -------------------------------------------------------------------------
    JIRA_BASE_URL: str = "https://dishtech-dishtv.atlassian.net"  # VERIFIED ✅
    JIRA_USER_EMAIL: Optional[str] = None  # Auto-populated from SSO email
    JIRA_API_TOKEN: Optional[str] = None  # Set via environment variable

    # Optional overrides for specialized models
    AGENT_MODE_MODEL: Optional[str] = None
    AGENT_MODE_MAX_ITERS: int = 5
    SUMMARY_MODEL_ARN: Optional[str] = None
    REVIEW_MODEL_ARN: Optional[str] = None

    # Read from .env
    model_config = SettingsConfigDict(env_file=(".env", ".env.local"))

    # ============================================================================
    # MCP TOOL ENABLE/DISABLE FLAGS
    # ============================================================================
    ENABLE_BETAREPORT_MCP: bool = True  # VERIFIED ✅
    ENABLE_VIEWERSHIP_MCP: bool = True  # VERIFIED ✅ (but has Lambda runtime error)
    ENABLE_LOG_ASSIST_MCP: bool = True  # LOCAL DEV ONLY
    ENABLE_INTERNAL_TOOLS_MCP: bool = False  # DISABLED (placeholder endpoint)

    # ============================================================================
    # CORS / FRONTEND ORIGINS - CONFIGURED FOR 10.*.*.* NETWORKS ✅
    # ============================================================================
    # Includes localhost, specific 10.*.*.* IPs, and production domain
    # oauth2-proxy should also be configured to allow 10.*.*.* networks
    # ============================================================================
    CORS_ALLOWED_ORIGINS: list[str] = [
        # Local development
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        # Internal 10.*.*.* network IPs
        "http://10.79.83.40:3000",
        "http://10.79.83.40:3001",
        "http://10.79.85.35:3000",
        "http://10.79.85.35:3001",
        # Internal hostname
        "http://dsgpu3090-lambda-vector:3000",
        "http://dsgpu3090-lambda-vector:3001",
        "http://0.0.0.0",
        # Production
        "https://chat-agent.dishtv.technology",
        "http://chat-agent.dishtv.technology",
    ]

    # ============================================================================
    # NETWORK ACCESS NOTES FOR 10.*.*.* NETWORKS
    # ============================================================================
    # 1. Lambda Function URLs (betareport, viewership): Publicly accessible
    # 2. Sentry: Accessible via ingress (ds-testing-sentry.dishtv.technology)
    # 3. Atlassian (Confluence, Jira): Public cloud, accessible from anywhere
    # 4. GitLab: Public, accessible from anywhere
    # 5. CART/CCTools/Portal: Likely require VPN or internal network
    # 6. oauth2-proxy: Should be configured to allow 10.*.*.* source IPs
    # ============================================================================

# ============================================================================
# MCP TIMEOUT SETTINGS - Added 2026-02-16
# ============================================================================
# Viewership queries can take 30-60+ seconds for large datasets
# Increase timeouts to prevent premature disconnection
MCP_DEFAULT_TIMEOUT_SECONDS: int = 300  # 5 minutes
MCP_SSE_READ_TIMEOUT_SECONDS: int = 300  # 5 minutes
