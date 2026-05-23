from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class SearchProfileBase(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    negative_keywords: List[str] = Field(default_factory=list)
    is_active: bool = True

class SearchProfileCreate(SearchProfileBase):
    pass

class SearchProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    keywords: Optional[List[str]] = None
    negative_keywords: Optional[List[str]] = None
    is_active: Optional[bool] = None

class SearchProfileResponse(SearchProfileBase):
    id: int

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
