"""매수 검증용 주변 컨텍스트 Pydantic (선택적 엄격 검증)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StockContextPayload(BaseModel):
    """FDR·플래그 등에서 온 종목 컨텍스트."""

    model_config = ConfigDict(extra="ignore")

    daily_change_pct: float | None = None
    consecutive_up_days: int = Field(0, ge=0, le=30)
    last_close: float | None = None
    warnings: list[str] = Field(default_factory=list)
    using_leverage: bool = False
    community_chase: bool = False
    recent_avg_down: bool = False

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StockContextPayload:
        return cls.model_validate(data)
