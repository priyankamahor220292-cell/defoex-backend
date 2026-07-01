import os
from datetime import timedelta
from dotenv import load_dotenv
from urllib.parse import quote_plus

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "defoex-secret-2026")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "defoex-jwt-2026")

    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    DATABASE_URL = os.getenv("DATABASE_URL")

    if DATABASE_URL:
        uri = DATABASE_URL
        if uri.startswith("postgres://"):
            uri = "postgresql+psycopg://" + uri[len("postgres://"):]
        elif uri.startswith("postgresql://") and "+" not in uri.split("://", 1)[0]:
            uri = "postgresql+psycopg://" + uri[len("postgresql://"):]
        SQLALCHEMY_DATABASE_URI = uri

    else:
        DB_HOST = os.getenv("DB_HOST", "localhost")
        DB_PORT = os.getenv("DB_PORT", "5432")
        DB_NAME = os.getenv("DB_NAME", "defoex_db")
        DB_USER = os.getenv("DB_USER", "priyankamahor")

        # Encode special chars like @
        DB_PASSWORD = quote_plus(
            os.getenv("DB_PASSWORD", "")
        )

        SQLALCHEMY_DATABASE_URI = (
            f"postgresql+psycopg://"
            f"{DB_USER}:{DB_PASSWORD}"
            f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_AS_ASCII = False

    CORS_ORIGINS = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000"
    ).split(",")