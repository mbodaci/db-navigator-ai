"""Configuration for DB-Navigator AI."""
import os
from dotenv import load_dotenv

load_dotenv()

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://dbnavigator:dbnavigator_dev@localhost:5432/dbnavigator"
)
BANK_SCHEMA = "bank"

# LLM - default to GPT-4o-mini for development (cheapest)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")  # openai, anthropic, google
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Model selection per provider
LLM_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-20241022",
    "google": "gemini-2.0-flash",
}

# Embedding model (local, free)
EMBEDDING_MODEL = "all-mpnet-base-v2"
EMBEDDING_DIM = 768

# RAG settings
RAG_TOP_K = 10  # number of items to retrieve per collection