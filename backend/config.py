from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_key: str = ""
    redis_url: str = "redis://localhost:6379"
    gemini_api_key: str = ""
    agent_model_base_url: str = "http://localhost:8080/v1"
    agent_model_api_key: str = "dummy"
    agent_model_name: str = "gemma4"
    vertex_project: str = ""
    vertex_location: str = "us-central1"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
