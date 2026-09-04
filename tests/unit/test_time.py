from services.brain.tools.time import TimeTool
import re
import pytest

def test_time_tool_returns_string():
    tool = TimeTool()
    
    result = tool.execute()
    
    assert isinstance(result, str)

def test_time_tool_returns_valid_time_format():
    tool = TimeTool()

    result = tool.execute()

    assert re.fullmatch(
        r"(0[1-9]|1[0-2]):[0-5][0-9]:[0-5][0-9] (AM|PM)",
        result,
    )
    
from datetime import datetime, timezone, timedelta

import services.brain.tools.time as time_module


def test_time_tool_returns_current_local_time(monkeypatch):
    class FakeDateTime:
        @classmethod
        def now(cls):
            return datetime(
                2026,
                8,
                29,
                15,
                30,
                45,
                tzinfo=timezone(timedelta(hours=5, minutes=30)),
            )

    monkeypatch.setattr(time_module, "datetime", FakeDateTime)

    tool = time_module.TimeTool()

    assert tool.execute() == "03:30:45 PM"
    
def test_time_tool_uses_local_timezone():
    class FakeDateTime:
        @classmethod
        def now(cls):
            return datetime(
                2026,
                8,
                29,
                15,
                30,
                45,
            )

        def astimezone(self):
            return datetime(
                2026,
                8,
                29,
                15,
                30,
                45,
            )

    monkeypatch = pytest.MonkeyPatch()

    try:
        monkeypatch.setattr(time_module, "datetime", FakeDateTime)

        tool = time_module.TimeTool()

        assert tool.execute() == "03:30:45 PM"
    finally:
        monkeypatch.undo()