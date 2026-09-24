from pydantic import BaseModel, Field


class LeadCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=3, max_length=320)
    company: str = Field(default="", max_length=200)


class Lead(LeadCreate):
    id: str
    score: int = 0
