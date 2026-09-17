from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "ECHO"
    app_version: str = "0.1.0"
    app_env: str = "development"
    
        
    ollama_host: str ="http://localhost:11434"
    ollama_model: str = "qwen3:0.6b"
    
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    
    ai_provider: str = "ollama"
    
    chroma_path: str = "data/chroma"
    embedding_provider: str = "default"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding= "utf-8",
        case_sensitive=False,
    )
    
settings = Settings()