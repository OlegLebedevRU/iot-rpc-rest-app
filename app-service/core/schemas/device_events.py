from pydantic import BaseModel


class DevEventBody(BaseModel):
    device_id: int
    event_type_code: int
    dev_event_id: int
    dev_timestamp: int
    payload: str


class DevEvents(DevEventBody):
    id: int
