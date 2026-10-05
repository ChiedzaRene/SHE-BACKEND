from pydantic import BaseModel, Field


class SafetyTargetsUpdate(BaseModel):
    # Bounds only guard against typos; real limits are a few units at most
    trir_limit: float = Field(..., gt=0, le=100)
    ltifr_limit: float = Field(..., gt=0, le=100)


class SafetyTargets(BaseModel):
    trir_limit: float
    ltifr_limit: float
    rate_basis_hours: int
    recordable_rule: str
    lost_time_rule: str
