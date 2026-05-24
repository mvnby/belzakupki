from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime

class SearchProfileBase(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    preset_code: Optional[str] = None
    niche_description: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    negative_keywords: List[str] = Field(default_factory=list)
    regions: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    min_score: float = 0.0
    is_active: bool = True
    schedule_interval: Optional[str] = None

class SearchProfileCreate(SearchProfileBase):
    pass

class SearchProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    preset_code: Optional[str] = None
    niche_description: Optional[str] = None
    keywords: Optional[List[str]] = None
    negative_keywords: Optional[List[str]] = None
    regions: Optional[List[str]] = None
    categories: Optional[List[str]] = None
    min_score: Optional[float] = None
    is_active: Optional[bool] = None
    schedule_interval: Optional[str] = None

class SearchProfileResponse(SearchProfileBase):
    id: int
    last_run_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class NotificationChannelBase(BaseModel):
    type: str = Field(..., max_length=64)
    name: str = Field(..., max_length=255)
    config: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True

class NotificationChannelCreate(NotificationChannelBase):
    pass

class NotificationChannelResponse(NotificationChannelBase):
    id: int
    profile_id: int

    class Config:
        from_attributes = True


class MatchStatusUpdate(BaseModel):
    status: str
