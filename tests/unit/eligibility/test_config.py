import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from customer_service.eligibility.config import EligibilityRuleConfig

ROOT = Path(__file__).parents[3]
CONFIG_PATH = ROOT / "config" / "return-eligibility-rules.v1.json"


def test_fixed_rule_config_has_version_and_inclusive_high_value_threshold() -> None:
    config = EligibilityRuleConfig.from_json(CONFIG_PATH)

    assert config.rule_version == "1.0.0"
    assert str(config.high_value.threshold) == "5000.00"
    assert config.is_high_value(currency="CNY", total_amount="5000.00")
    assert not config.is_high_value(currency="CNY", total_amount="4999.99")


def test_rule_config_rejects_non_positive_threshold(tmp_path: Path) -> None:
    document = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    document["high_value"]["threshold"] = "0.00"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValidationError):
        EligibilityRuleConfig.from_json(path)
