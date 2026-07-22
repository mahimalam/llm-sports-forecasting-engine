import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "eap_sports.db"
GCP_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
GCP_PROJECT = os.getenv("GCP_PROJECT_ID", "new-n8n-project-490407")
GCP_REGION = os.getenv("GCP_REGION", "us-central1")
FOOTBALL_DATA_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADSGRAM_BLOCK_ID = os.getenv("ADSGRAM_BLOCK_ID", "34584")
