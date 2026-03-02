# schemas/postamat.py
from datetime import datetime
from typing import Optional, Dict, List
from pydantic import BaseModel


class DeviceShortSchema(BaseModel):
    sn: str
    created_at: datetime

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"sn": "a3b0000000c99999d250813", "created_at": "2024-01-01T10:00:00"}
            ]
        }
    }


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


class CellLockRequest(BaseModel):
    id: int
    is_locked: bool


class CellAttributesRequest(BaseModel):
    id: int
    attributes: Dict[str, object]


class CellResponse(BaseModel):
    id: int
    #  postamat_id: int
    number: int
    size: str
    is_locked: bool
    attributes: Optional[Dict] = None
    #  created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    #  is_deleted: bool = False
    #  deleted_at: Optional[datetime] = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": 101,
                    "number": 1,
                    "size": "M",
                    "is_locked": False,
                    "attributes": {
                        "ir_sensor": True,
                        "storage": {"id": 1234, "status": "blocked"},
                    },
                }
            ]
        }
    }


class PostamatWithCellsResponse(BaseModel):
    id: int
    device_id: int
    name: Optional[str]
    address: Optional[str]
    location: Optional[Dict[str, float]]
    created_at: Optional[str]
    updated_at: Optional[str]
    is_deleted: bool
    deleted_at: Optional[str]
    device: Optional[DeviceShortSchema] = None
    cells: List[CellResponse] = []

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "device_id": 101,
                    "name": "Постамат у метро",
                    "address": "г. Москва, м. Курская, ул. Земляной Вал, д. 7",
                    "location": {"lat": 55.7617, "lng": 37.6807},
                    "created_at": "2024-01-01T10:00:00",
                    "updated_at": "2024-01-16T09:15:00",
                    "is_deleted": False,
                    "deleted_at": None,
                    "device": {
                        "sn": "a3b0000000c99999d250813",
                        "created_at": "2024-01-01T10:00:00",
                    },
                    "cells": [
                        {
                            "id": 101,
                            "number": 1,
                            "size": "M",
                            "is_locked": False,
                            "attributes": {
                                "ir_sensor": True,
                                "storage": {"id": 1234, "status": "blocked"},
                            },
                            "updated_at": "2024-01-15T14:20:00",
                        },
                        {
                            "id": 102,
                            "number": 2,
                            "size": "L",
                            "is_locked": True,
                            "attributes": {
                                "ir_sensor": True,
                                "storage": {"id": 1235, "status": "ready"},
                            },
                            "updated_at": "2024-01-16T09:15:00",
                        },
                    ],
                }
            ]
        }
    }


class PostamatShortSchema(BaseModel):
    id: int
    device_id: int
    name: Optional[str] = None
    address: Optional[str] = None
    location: Optional[Dict[str, float]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    device: Optional[DeviceShortSchema] = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "device_id": 101,
                    "name": "Постамат у метро",
                    "address": "г. Москва, м. Курская, ул. Земляной Вал, д. 7",
                    "location": {"lat": 55.7617, "lng": 37.6807},
                    "created_at": "2024-01-01T10:00:00",
                    "updated_at": "2024-01-02T15:30:00",
                    "device": {
                        "sn": "a3b0000000c99999d250813",
                        "created_at": "2024-01-01T10:00:00",
                    },
                },
                {
                    "id": 2,
                    "device_id": 102,
                    "name": "Постамат в ТЦ",
                    "address": "г. Санкт-Петербург, Невский пр., д. 20",
                    "location": {"lat": 59.9343, "lng": 30.3351},
                    "created_at": "2024-01-03T09:15:00",
                    "updated_at": "2024-01-03T09:15:00",
                    "device": {
                        "sn": "a3b0000000c99999d250813",
                        "created_at": "2024-01-03T09:00:00",
                    },
                },
            ]
        }
    }


class PostamatCmd(BaseModel):
    method: str
    params: Dict

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "method": "open_cells",
                    "params": {"cell_numbers": [1, 2]},
                }
            ]
        }
    }

    # class Config:
    #     from_attributes = True  # ранее orm_mode = True
