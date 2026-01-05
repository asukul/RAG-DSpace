"""
Configuration settings for ISU Research Search backend.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # API Keys
    gemini_api_key: str = ""
    
    # DSpace Configuration
    dspace_base_url: str = "https://dr.lib.iastate.edu"
    dspace_api_url: str = ""  # Will be computed
    
    # Redis Configuration
    redis_url: str = "redis://localhost:6379"
    cache_ttl: int = 3600  # 1 hour
    
    # Server Configuration
    log_level: str = "INFO"
    frontend_url: str = "http://localhost:3000"
    
    # Rate Limiting
    rate_limit_requests: int = 100
    rate_limit_window: int = 60  # seconds
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.dspace_api_url:
            self.dspace_api_url = f"{self.dspace_base_url}/server/api"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Export settings instance
settings = get_settings()
