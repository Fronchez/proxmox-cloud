import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import text

from app.routers import vms, lxc, auth
from app.database import engine
from app.models import Base


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """События при запуске и остановке приложения."""
    # При запуске создаём таблицы БД
    logger.info("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Добавляем колонку password если нет
    logger.info("Checking password column...")
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'vms' AND column_name = 'password'
        """))
        if not result.fetchone():
            await conn.execute(text("ALTER TABLE vms ADD COLUMN password VARCHAR"))
            logger.info("✅ Added password column to vms table")
        else:
            logger.info("✅ Password column already exists")
    
    logger.info("Database tables created successfully")
    yield
    # При остановке можно добавить очистку ресурсов
    logger.info("Shutting down...")


app = FastAPI(title="Proxmox Cloud", lifespan=lifespan)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене укажите конкретные origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(vms.router, prefix="/vms", tags=["VMs"])
app.include_router(lxc.router, prefix="/lxc", tags=["LXC"])


@app.get("/")
async def root():
    return {"message": "Proxmox Cloud API", "status": "running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
