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
    tenant_id: Optional[int] = None
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


class TenantResponse(BaseModel):
    id: int
    name: str
    is_active: bool

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=6, max_length=64)
    full_name: Optional[str] = Field(None, max_length=255)
    tenant_name: Optional[str] = Field(None, max_length=255)


class UserLogin(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    tenant_id: int
    email: str
    full_name: Optional[str] = None
    role: str
    is_active: bool

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CrmConfigBase(BaseModel):
    crm_type: str = Field(..., max_length=64)
    is_active: bool = True
    webhook_url: Optional[str] = Field(None, max_length=500)
    subdomain: Optional[str] = Field(None, max_length=255)
    api_token: Optional[str] = None
    custom_mappings: Optional[Dict[str, Any]] = None


class CrmConfigCreate(CrmConfigBase):
    pass


class CrmConfigResponse(CrmConfigBase):
    id: int
    tenant_id: int

    class Config:
        from_attributes = True


class ChatMessageCreate(BaseModel):
    message: str = Field(..., min_length=1)


class ChatMessageResponse(BaseModel):
    id: int
    role: str
    message: str
    created_at: datetime

    class Config:
        from_attributes = True


