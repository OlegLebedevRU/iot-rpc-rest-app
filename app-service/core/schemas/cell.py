# schemas/cell.py
from typing import Optional, Dict
from pydantic import BaseModel


class CellBase(BaseModel):
    number: int
    size_code: str
    alias: Optional[str] = None
    is_locked: Optional[bool] = None
    attributes: Optional[Dict] = None


class CellCreate(CellBase):
    pass


class CellUpdate(BaseModel):
    alias: Optional[str] = None
    is_locked: Optional[bool] = None
    attributes: Optional[Dict] = None
    # size_code и number не обновляем — они статичны
