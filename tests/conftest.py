import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sheet():
    return json.loads((FIXTURES / "redistribution_sheet.json").read_text())
