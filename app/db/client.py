from supabase import create_client, Client
from app.core.config import settings
from app.core.logging import logger

try:
    supabase_client: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    logger.info("Supabase client initialized successfully")
except Exception as e:
    logger.error("Failed to initialize Supabase client", extra={"error": str(e)})
    supabase_client = None
