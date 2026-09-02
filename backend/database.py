from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker,declarative_base,DeclarativeBase
from dotenv import load_dotenv 
import os 

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL is None:
    raise ValueError("DATABASE_URL environment variable is not set. Check your .env file.")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


class Base(DeclarativeBase):
    pass

try:
    with engine.connect() as connection:
        print("✅ Successfully connected to PostgreSQL!")
except Exception as e:
    print("❌ Database connection failed:")
    print(e)