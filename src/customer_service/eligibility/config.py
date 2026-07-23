import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field

PositiveMoney = Annotated[Decimal, Field(gt=0, decimal_places=2)]


class HighValueRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    currency: str = Field(min_length=3, max_length=3)
    threshold: PositiveMoney


class EligibilityRuleConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_version: str = Field(min_length=1)
    reference_date: date
    high_value: HighValueRule
    eligible_order_status: str = Field(min_length=1)
    resalable_item_condition: str = Field(min_length=1)

    @classmethod
    def from_json(cls, path: Path) -> Self:
        document = json.loads(path.read_text(encoding="utf-8"))
        return cls.model_validate(document)

    def is_high_value(self, *, currency: str, total_amount: str) -> bool:
        return (
            currency == self.high_value.currency
            and Decimal(total_amount) >= self.high_value.threshold
        )
