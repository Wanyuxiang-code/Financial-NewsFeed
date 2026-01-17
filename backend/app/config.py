"""Pydantic Settings 配置管理"""
from typing import List, Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置 - 从环境变量和 .env 文件加载"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,  # 允许使用 alias
    )
    
    # ===== App Settings =====
    app_name: str = "NewsFeed"
    app_version: str = "0.1.0"
    debug: bool = False
    
    # ===== Database =====
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/newsfeed.db",
        description="Database connection URL"
    )
    
    # ===== AI Provider =====
    ai_provider: Literal["gemini", "openai", "claude", "ollama"] = "gemini"
    
    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-pro"
    gemini_api_endpoint: str = ""  # 自定义 API 代理地址，如 http://127.0.0.1:8045
    
    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    
    # Claude
    claude_api_key: str = ""
    claude_model: str = "claude-3-haiku-20240307"
    
    # Ollama (local)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    
    # ===== Data Sources =====
    # Finnhub
    finnhub_api_key: str = ""
    finnhub_enabled: bool = True
    
    # SEC EDGAR
    sec_enabled: bool = True
    sec_user_agent: str = Field(
        default="NewsFeed/1.0 (contact@example.com)",
        description="Required by SEC: App name and contact email"
    )
    
    # ===== Outputs =====
    # 逗号分隔格式: "notion,email,telegram"
    outputs_str: str = Field(default="notion", alias="outputs")
    
    @property
    def outputs(self) -> List[str]:
        """解析 outputs 为列表"""
        if not self.outputs_str or self.outputs_str.strip() == "":
            return []
        return [x.strip() for x in self.outputs_str.split(",") if x.strip()]
    
    # Notion
    notion_token: str = ""
    notion_database_id: str = ""
    
    # Email (optional)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_to: str = ""
    
    # Telegram (optional)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    
    # ===== Scheduling =====
    digest_hours_lookback: int = Field(
        default=24,
        description="Hours of news to collect in each digest"
    )
    
    # ===== Rate Limits (requests per minute) =====
    finnhub_rate_limit: int = 60
    sec_rate_limit: int = 600  # 10/s = 600/min
    notion_rate_limit: int = 180  # 3/s = 180/min
    gemini_rate_limit: int = 60
    openai_rate_limit: int = 60
    
    # ===== Paths =====
    watchlist_path: str = "data/watchlist.yaml"
    prompts_dir: str = "data/prompts"
    
    @property
    def current_ai_api_key(self) -> str:
        """获取当前选择的 AI Provider 的 API Key"""
        return {
            "gemini": self.gemini_api_key,
            "openai": self.openai_api_key,
            "claude": self.claude_api_key,
            "ollama": "",
        }.get(self.ai_provider, "")
    
    @property
    def current_ai_model(self) -> str:
        """获取当前选择的 AI Provider 的模型名"""
        return {
            "gemini": self.gemini_model,
            "openai": self.openai_model,
            "claude": self.claude_model,
            "ollama": self.ollama_model,
        }.get(self.ai_provider, "")


# Global settings instance
settings = Settings()
