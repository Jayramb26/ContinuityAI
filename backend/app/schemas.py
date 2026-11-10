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
    title: str | None = None
    detail: str | None = None
    status: str | None = None
    verified: bool | None = None
    owner: str | None = None
    due_date: str | None = None
    priority: str | None = None
    work_status: str | None = None

class KnowledgeCreate(BaseModel):
    category: str
    title: str
    detail: str = ""
    owner: str = ""
    due_date: str = ""
    priority: str = "medium"
    work_status: str = "open"
    evidence: str = ""

class ActivityCreate(BaseModel):
    message: str
    event_type: str = "update"
