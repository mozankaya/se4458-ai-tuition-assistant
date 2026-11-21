"""Agent settings loaded from environment variables or the repository-level .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

# Both providers are called through the OpenAI-compatible Chat Completions API.
PROVIDER_BASE_URLS = {
    "openai": None,  # SDK default: https://api.openai.com/v1
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}
DEFAULT_MODELS = {"openai": "gpt-4o-mini", "gemini": "gemini-3.5-flash-lite"}


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", ".env"), env_file_encoding="utf-8", extra="ignore")

    llm_provider: str = "gemini"
    llm_model: str = ""
    llm_base_url: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    llm_temperature: float = 0.0

    gateway_base_url: str = "http://localhost:8000"
    mcp_server_url: str = "http://localhost:8001/mcp"
    trace_dir: Path = REPO_ROOT / "docs" / "traces"

    @property
    def resolved_model(self) -> str:
        return self.llm_model or DEFAULT_MODELS[self.llm_provider]

    @property
    def resolved_base_url(self) -> str | None:
        return self.llm_base_url or PROVIDER_BASE_URLS[self.llm_provider]

    @property
    def api_key(self) -> str:
        return self.gemini_api_key if self.llm_provider == "gemini" else self.openai_api_key

    def validate_llm(self) -> None:
        if self.llm_provider not in PROVIDER_BASE_URLS:
            raise ValueError(f"LLM_PROVIDER must be one of {sorted(PROVIDER_BASE_URLS)}")
        if not self.api_key:
            raise ValueError(f"{self.llm_provider.upper()}_API_KEY is not set (see .env.example)")


@lru_cache
def get_settings() -> AgentSettings:
    return AgentSettings()
