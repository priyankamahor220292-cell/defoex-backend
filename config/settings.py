import os
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv
from sqlalchemy.engine import URL

# Load .env explicitly
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

print(f"Loading .env from: {ENV_FILE}")

load_dotenv(dotenv_path=ENV_FILE)

print("====================================")
print("DB_HOST =", os.getenv("DB_HOST"))
print("DB_PORT =", os.getenv("DB_PORT"))
print("DB_NAME =", os.getenv("DB_NAME"))
print("DB_USER =", os.getenv("DB_USER"))
print("DB_PASSWORD =", os.getenv("DB_PASSWORD"))
print("====================================")


class Config:
    SECRET_KEY = os.getenv(
        "SECRET_KEY",
        "defoex-secret-2024"
    )

    JWT_SECRET_KEY = os.getenv(
        "JWT_SECRET_KEY",
        "defoex-jwt-secret-2024"
    )

    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "3306")
    DB_NAME = os.getenv("DB_NAME", "defoex_db")
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")

    SQLALCHEMY_DATABASE_URI = URL.create(
        drivername="mysql+pymysql",
        username=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=int(DB_PORT),
        database=DB_NAME
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    CORS_ORIGINS = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000"
    ).split(",")


print("\nConnection String:")
print(Config.SQLALCHEMY_DATABASE_URI)
print()