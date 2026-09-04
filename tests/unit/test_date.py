from services.brain.tools.date import DateTool
from datetime import datetime
import re
import services.brain.tools.date as date_module

def test_date_tool_returns_string():
    tool = DateTool()

    result = tool.execute()

    assert isinstance(result, str)

def test_date_tool_returns_valid_date_format():
    tool = DateTool()

    result = tool.execute()

    assert re.fullmatch(
        r"\d{2}-\d{2}-\d{4}",
        result,
    )
    
def test_date_tool_returns_current_date(monkeypatch):
    class FakeDateTime:
        @classmethod
        def now(cls):
            return datetime(2026, 8, 29)

    monkeypatch.setattr(date_module, "datetime", FakeDateTime)

    tool = date_module.DateTool()

    assert tool.execute() == "29-08-2026"
    
def test_date_tool_pads_single_digit_day_and_month(monkeypatch):
    class FakeDateTime:
        @classmethod
        def now(cls):
            return datetime(2026, 1, 5)

    monkeypatch.setattr(date_module, "datetime", FakeDateTime)

    tool = date_module.DateTool()

    assert tool.execute() == "05-01-2026"
    
