from pydantic import BaseModel, ConfigDict

class ProjectCreate(BaseModel):
    name: str
    description: str = ""

class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    created_at: str | None = None

class ReviewUpdate(BaseModel):
    title: str
    detail: str
    status: str
    verified: bool = False
