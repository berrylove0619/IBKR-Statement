from pydantic import BaseModel


class BootstrapStatusResponse(BaseModel):
    initialized: bool
    auth_source: str


class BootstrapInitRequest(BaseModel):
    username: str
    password: str


class BootstrapInitResponse(BaseModel):
    initialized: bool
