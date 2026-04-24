import os
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from dotenv import load_dotenv

load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL")

client = AsyncIOMotorClient(MONGODB_URL)
db = client["speak2me-fitness"]


async def test_mongo_connection():
    try:
        await client.admin.command("ping")
        print("MongoDB connected successfully")
        return True
    except Exception as e:
        print(f"Failed to connect to MongoDB: {e}")
        return False


async def init_db():
    from backend.models import Correction, FoodLog, UserProfile
    await init_beanie(database=db, document_models=[FoodLog, UserProfile, Correction])

async def close_mongo_connection():
    client.close()