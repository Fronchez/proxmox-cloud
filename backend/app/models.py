from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class VM(Base):
    __tablename__ = "vms"

    id = Column(Integer, primary_key=True)
    vmid = Column(Integer, unique=True)
    name = Column(String)
    type = Column(String)
    os = Column(String)
    ip = Column(String)
    status = Column(String)
    password = Column(String)  # Пароль от VM/LXC


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)