from pydantic import BaseModel, EmailStr


class UserBase(BaseModel):
    id: int
    name: str
    password: str

class UserAdd(BaseModel):
    name: str
    password: str


class RepositoryItem(BaseModel):
    id: int
    name: str
    link: str
    user_id: int


class FileItem(BaseModel):
    id: int
    name: str
    download_link: str
    rep_id: int


class Token(BaseModel):
    access_token: str
    token_type: str
