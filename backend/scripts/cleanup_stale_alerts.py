import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import asyncio
from datetime import datetime, timezone
from app.database.mongodb import get_database, connect_to_mongo

async def cleanup():
    await connect_to_mongo()
    db = get_database()
    res = await db.alerts.update_many(
        {"status": "ACTIVE"},
        {"$set": {"status": "RESOLVED", "resolved_at": datetime.now(timezone.utc), "resolved_by": "system_cleanup"}}
    )
    print(f"Resolved {res.modified_count} stale active alerts.")

if __name__ == "__main__":
    asyncio.run(cleanup())
