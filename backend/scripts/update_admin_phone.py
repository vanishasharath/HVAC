import asyncio
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.database.mongodb import connect_to_mongo, get_database, close_mongo_connection

async def main():
    await connect_to_mongo()
    db = get_database()
    result = await db.users.update_many(
        {"role": "ADMIN"},
        {"$set": {"phone_number": "+919449471959"}}
    )
    print(f"Successfully updated {result.modified_count} admin accounts to +919449471959")
    admins = await db.users.find({"role": "ADMIN"}, {"email": 1, "role": 1, "phone_number": 1}).to_list(10)
    for admin in admins:
        print(f"  - {admin.get('email')}: {admin.get('phone_number')}")
    await close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(main())
