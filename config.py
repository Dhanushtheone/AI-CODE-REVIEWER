"""Configuration loader — reads GROQ_API_KEY from .env or environment."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
