"""외부·설정 기반 입력 Pydantic 검증 (SQL/코드 인젝션 방지: 문자열은 식별자만 허용)."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


class OrderIntent(BaseModel):
    """주문 의도 (종목·수량)."""

    symbol: str = Field(..., min_length=6, max_length=6, description="6자리 종목코드")
    qty: int = Field(..., ge=1, le=500_000)

    @field_validator("symbol")
    @classmethod
    def digits_only(cls, v: str) -> str:
        if not re.fullmatch(r"\d{6}", v):
            raise ValueError("symbol은 숫자 6자리만 허용")
        return v


class AccountProductCode(BaseModel):
    code: str = Field(..., min_length=2, max_length=2)

    @field_validator("code")
    @classmethod
    def two_digits(cls, v: str) -> str:
        if not re.fullmatch(r"\d{2}", v):
            raise ValueError("PRODUCT_CODE는 숫자 2자리")
        return v
