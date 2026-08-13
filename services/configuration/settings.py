from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "ECHO"
    app_version: str = "0.1.0"
    app_env: str = "development"
    
        
    ollama_host: str ="http://localhost:11434"
    ollama_model: str = "qwen3:0.6b"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding= "utf-8",
        case_sensitive=False,
    )
    
settings = Settings()