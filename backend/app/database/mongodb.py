from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings


class MongoDB:
    client: AsyncIOMotorClient = None
    db = None


mongodb = MongoDB()


async def connect_to_mongo():
    mongodb.client = AsyncIOMotorClient(settings.mongodb_url)
    mongodb.db = mongodb.client[settings.mongodb_db_name]


async def close_mongo_connection():
    if mongodb.client:
        mongodb.client.close()


def get_database():
    return mongodb.db
