from __future__ import annotations

from datetime import datetime
from ipaddress import IPv4Address
from typing import Any
from pydantic import BaseModel, ConfigDict


class ClientId(BaseModel):
    model_config = ConfigDict(extra="allow")
    client_id: str | None = None


class ClientProperties(BaseModel):
    model_config = ConfigDict(extra="allow")
    client_properties: ClientId | dict[str, Any] | None = None


class DeviceConnectionDetails(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="allow")
    user: str | None = None
    name: str | None = None
    conn_name: str | None = None
    connected_at: int | datetime | None = None
    peer_host: IPv4Address | str | None = None
    peer_port: int | None = None
    peer_cert_subject: str | None = None
    protocol: str | None = None
    peer_cert_validity: str | None = None
    ssl: bool | None = None
    ssl_cipher: str | None = None
    ssl_protocol: str | None = None
    bytes_received: int | None = None
    bytes_sent: int | None = None
    recv_oct: int | None = None
    send_oct: int | None = None
    client_properties: ClientId | dict[str, Any] | None = None


class RmqClientsAction(BaseModel):
    action: str
    clients: list[str]
