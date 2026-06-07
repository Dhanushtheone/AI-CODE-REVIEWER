import os

try:
	from dotenv import load_dotenv
	load_dotenv()
except Exception:
	pass

# Load GROQ API key from environment. Set in your local `.env` or in the environment.
GROQ_API_KEY = os.getenv("GROQ_API_KEY")