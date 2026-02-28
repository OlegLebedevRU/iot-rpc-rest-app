# schemas/postamat.py
from typing import Optional, Dict
from pydantic import BaseModel


class PostamatBase(BaseModel):
    device_id: int
    name: str
    address: Optional[str] = None
    location: Optional[Dict] = None  # например, {"lat": 55.7558, "lon": 37.6176}


class PostamatCreate(PostamatBase):
    pass


class PostamatUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    location: Optional[Dict] = None
    # is_deleted можно обновлять только через специальные методы
