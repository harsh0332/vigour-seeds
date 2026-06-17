import asyncio
import sys
from app.core.logging import logger
from app.services.followup import followup_service

async def main():
    logger.info("Scheduler worker started")
    try:
        sent_count = await followup_service.process_due_followups()
        logger.info("Scheduler worker completed successfully", extra={"sent_count": sent_count})
    except Exception as e:
        logger.error("Scheduler worker failed with exception", extra={"error": str(e)})
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
