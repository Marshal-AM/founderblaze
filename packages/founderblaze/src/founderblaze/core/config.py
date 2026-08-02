from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    port: int = Field(default=4021, alias="PORT")
    public_api_base_url: str = Field(
        default="http://localhost:4021",
        alias="PUBLIC_API_BASE_URL",
    )

    # Agent + MCP
    agent_port: int = Field(default=4022, alias="AGENT_PORT")
    founderblaze_a2mcp_base_url: str = Field(
        default="http://localhost:4021",
        alias="FOUNDERBLAZE_A2MCP_BASE_URL",
    )
    agent_cors_origins: str = Field(
        default="http://localhost:3001",
        alias="AGENT_CORS_ORIGINS",
    )
    agent_job_timeout_seconds: float = Field(
        default=1800.0,
        alias="AGENT_JOB_TIMEOUT_SECONDS",
    )

    # Jobs DB (required for api/worker; optional for agent/MCP CLI)
    database_url: str = Field(default="", alias="DATABASE_URL")

    # Temporal
    temporal_address: str = Field(default="localhost:7233", alias="TEMPORAL_ADDRESS")
    temporal_namespace: str = Field(default="default", alias="TEMPORAL_NAMESPACE")
    temporal_task_queue: str = Field(default="founderblaze", alias="TEMPORAL_TASK_QUEUE")
    temporal_api_key: str | None = Field(default=None, alias="TEMPORAL_API_KEY")
    temporal_tls: bool = Field(default=False, alias="TEMPORAL_TLS")

    # Backblaze B2 (via genblaze-s3)
    b2_key_id: str = Field(default="", alias="B2_KEY_ID")
    b2_app_key: str = Field(default="", alias="B2_APP_KEY")
    b2_bucket: str = Field(default="", alias="B2_BUCKET")
    b2_region: str = Field(default="us-west-004", alias="B2_REGION")
    b2_public_url_base: str = Field(default="", alias="B2_PUBLIC_URL_BASE")
    b2_url_ttl_seconds: int = Field(default=604800, alias="B2_URL_TTL_SECONDS")

    # Vendors
    lmnt_api_key: str = Field(default="", alias="LMNT_API_KEY")
    lmnt_voice: str = Field(default="lily", alias="LMNT_VOICE")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_text_model: str = Field(
        default="gemini-2.5-flash",
        alias="GEMINI_TEXT_MODEL",
    )
    # Agent chat/tool-loop model (defaults to Gemini 3.1 Pro for reliable tool use).
    agent_gemini_model: str = Field(
        default="gemini-3.1-pro-preview",
        alias="AGENT_GEMINI_MODEL",
    )
    gemini_image_model: str = Field(
        default="gemini-2.5-flash-image",
        alias="GEMINI_IMAGE_MODEL",
    )

    @property
    def resolved_agent_gemini_model(self) -> str:
        return (self.agent_gemini_model or self.gemini_text_model).strip()
    veo_model: str = Field(
        default="veo-3.1-generate-preview",
        alias="VEO_MODEL",
    )
    segmind_api_key: str = Field(default="", alias="SEGMIND_API_KEY")
    firecrawl_api_key: str = Field(default="", alias="FIRECRAWL_API_KEY")
    exa_search_api_key: str = Field(default="", alias="EXA_SEARCH_API_KEY")
    exa_api_key: str = Field(default="", alias="EXA_API_KEY")
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    jina_api_key: str = Field(default="", alias="JINA_API_KEY")
    serper_api_key: str = Field(default="", alias="SERPER_API_KEY")
    brave_search_api_key: str = Field(default="", alias="BRAVE_SEARCH_API_KEY")

    @property
    def resolved_exa_api_key(self) -> str:
        return (self.exa_search_api_key or self.exa_api_key or "").strip()

    def require_b2(self) -> None:
        missing = [
            name
            for name, val in (
                ("B2_KEY_ID", self.b2_key_id),
                ("B2_APP_KEY", self.b2_app_key),
                ("B2_BUCKET", self.b2_bucket),
            )
            if not val.strip()
        ]
        if missing:
            raise RuntimeError(f"Missing required B2 env: {', '.join(missing)}")

    def require_apd_vendors(self) -> None:
        missing = [
            name
            for name, val in (
                ("LMNT_API_KEY", self.lmnt_api_key),
                ("GEMINI_API_KEY", self.gemini_api_key),
                ("FIRECRAWL_API_KEY", self.firecrawl_api_key),
            )
            if not val.strip()
        ]
        if missing:
            raise RuntimeError(f"Missing required APD env: {', '.join(missing)}")

    def require_brand_kit_vendors(self) -> None:
        if not self.gemini_api_key.strip():
            raise RuntimeError("Missing required brand-kit env: GEMINI_API_KEY")

    def require_outreach_vendors(self) -> None:
        missing = []
        if not self.gemini_api_key.strip():
            missing.append("GEMINI_API_KEY")
        if not self.resolved_exa_api_key:
            missing.append("EXA_SEARCH_API_KEY")
        if missing:
            raise RuntimeError(
                f"Missing required outreach env: {', '.join(missing)}"
            )

    def require_social_listening_vendors(self) -> None:
        missing = []
        if not self.gemini_api_key.strip():
            missing.append("GEMINI_API_KEY")
        if not self.tavily_api_key.strip():
            missing.append("TAVILY_API_KEY")
        if missing:
            raise RuntimeError(
                f"Missing required social-listening env: {', '.join(missing)}"
            )

    def require_promo_video_vendors(self) -> None:
        missing = []
        if not self.gemini_api_key.strip():
            missing.append("GEMINI_API_KEY")
        if not self.segmind_api_key.strip():
            missing.append("SEGMIND_API_KEY")
        if missing:
            raise RuntimeError(
                f"Missing required promo-video env: {', '.join(missing)}"
            )

    def require_competitor_research_vendors(self) -> None:
        """Gemini required. Prefer Serper or Brave; DuckDuckGo is last-resort search."""
        missing: list[str] = []
        if not self.gemini_api_key.strip():
            missing.append("GEMINI_API_KEY")
        if not self.serper_api_key.strip() and not self.brave_search_api_key.strip():
            # DDG still works without keys; require a paid search key for production quality.
            missing.append("SERPER_API_KEY or BRAVE_SEARCH_API_KEY")
        if missing:
            raise RuntimeError(
                f"Missing required competitor-research env: {', '.join(missing)}"
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
