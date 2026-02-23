from pydantic import BaseModel
from typing import Optional

# VM схемы
class VMCreate(BaseModel):
    name: str
    os: Optional[str] = "ubuntu-22.04"
    cpu: Optional[int] = 1
    memory: Optional[int] = 2048
    disk: Optional[int] = 10
    type: Optional[str] = "qemu"  # qemu или lxc

class VMResponse(BaseModel):
    vmid: int
    name: str
    type: str
    os: str
    cpu: int
    memory: int
    disk: int
    ip: Optional[str]
    status: Optional[str]
    password: Optional[str] = None  # Пароль

# Пользователь схемы
class UserCreate(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"