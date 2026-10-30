import logging
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings

logger = logging.getLogger("mongodb")


class MongoDB:
    client = None
    db = None
    is_mock: bool = False


mongodb = MongoDB()


async def seed_initial_data():
    """Seed initial administrator and demo HVAC unit if they do not already exist."""
    try:
        from app.security.password import hash_password

        # 1. Seed admin user
        default_users = [
            {
                "email": "dhruvi01@gmail.com",
                "hashed_password": hash_password("password123"),
                "full_name": "Dhruvi",
                "phone_number": "+919632132626",
                "phone_verified": False,
                "role": "ADMIN",
                "created_at": datetime.now(timezone.utc),
            },
            {
                "email": "admin@example.com",
                "hashed_password": hash_password("password123"),
                "full_name": "System Administrator",
                "phone_number": "+919632132626",
                "phone_verified": False,
                "role": "ADMIN",
                "created_at": datetime.now(timezone.utc),
            },
            {
                "email": "tech@example.com",
                "hashed_password": hash_password("password123"),
                "full_name": "Alex Rivera",
                "phone_number": "+14155552673",
                "phone_verified": False,
                "role": "TECHNICIAN",
                "created_at": datetime.now(timezone.utc),
            },
        ]

        for u in default_users:
            existing = await mongodb.db.users.find_one({"email": u["email"]})
            if not existing:
                await mongodb.db.users.insert_one(u)
                logger.info("Seeded default user: %s", u["email"])
            elif existing.get("phone_number") != u.get("phone_number") and u.get("phone_number"):
                await mongodb.db.users.update_one(
                    {"email": u["email"]},
                    {"$set": {"phone_number": u["phone_number"], "phone_verified": u.get("phone_verified", False)}},
                )
                logger.info("Updated existing default user phone_number: %s", u["email"])

        # 2. Seed default HVAC units
        demo_units = [
            {
                "hvac_id": "HVAC_TEST_01",
                "name": "Main Office Chiller #1",
                "location": "Building A - Roof",
                "refrigerant_type": "R-32",
                "capacity_tons": 50.0,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            },
            {
                "hvac_id": "HVAC_TEST_02",
                "name": "Server Room AC #2",
                "location": "Building B - Basement",
                "refrigerant_type": "R-32",
                "capacity_tons": 25.0,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            },
        ]

        for unit in demo_units:
            existing_unit = await mongodb.db.hvac_units.find_one({"hvac_id": unit["hvac_id"]})
            if not existing_unit:
                await mongodb.db.hvac_units.insert_one(unit)
                logger.info("Seeded default HVAC unit: %s", unit["hvac_id"])

    except Exception as exc:
        logger.warning("Failed to seed initial data: %s", exc)


async def connect_to_mongo():
    try:
        # Test real MongoDB with a fast 1.5s timeout so startup doesn't hang
        real_client = AsyncIOMotorClient(settings.mongodb_url, serverSelectionTimeoutMS=1500)
        await real_client.admin.command("ping")
        mongodb.client = real_client
        mongodb.db = mongodb.client[settings.mongodb_db_name]
        mongodb.is_mock = False
        logger.info("Connected to real MongoDB at %s", settings.mongodb_url)
    except Exception as exc:
        logger.warning(
            "Local MongoDB not reachable (%s). Falling back to in-memory database (mongomock-motor).",
            exc,
        )
        from mongomock_motor import AsyncMongoMockClient

        mongodb.client = AsyncMongoMockClient()
        mongodb.db = mongodb.client[settings.mongodb_db_name]
        mongodb.is_mock = True

    await seed_initial_data()


async def close_mongo_connection():
    if mongodb.client and not mongodb.is_mock:
        mongodb.client.close()


def get_database():
    return mongodb.db
