from ipaddress import IPv4Address
from pydantic import BaseModel, Field, ConfigDict


class ClientId(BaseModel):
    client_id: str = Field(min_length=23, max_length=23)


class ClientProperties(BaseModel):
    client_properties: ClientId


class DeviceConnectionDetails(ClientProperties):
    model_config = ConfigDict(from_attributes=True)
    user: str
    connected_at: int
    peer_host: IPv4Address
    peer_cert_subject: str
    protocol: str
    peer_cert_validity: str


class RmqClientsAction(BaseModel):
    action: str
    clients: list[str]
