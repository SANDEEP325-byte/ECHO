from packages.interfaces.request import Request, RequestStatus
from services.brain.request_analyzer import RequestAnalyzer


def test_analyzer_detects_intent():
    analyzer = RequestAnalyzer()

    request = Request(user_input="What time is it?")

    result = analyzer.analyze(request)

    assert result.intent == "time"
    assert result.status == RequestStatus.ANALYZING


def test_analyzer_sets_normal_priority():
    analyzer = RequestAnalyzer()

    request = Request(user_input="Hello ECHO")

    result = analyzer.analyze(request)

    assert result.priority == "normal"


def test_analyzer_detects_high_priority():
    analyzer = RequestAnalyzer()

    request = Request(
        user_input="This is urgent, help me immediately"
    )

    result = analyzer.analyze(request)

    assert result.priority == "high"


def test_analyzer_detects_simple_complexity():
    analyzer = RequestAnalyzer()

    request = Request(user_input="Hello ECHO")

    result = analyzer.analyze(request)

    assert result.complexity == "simple"


def test_analyzer_detects_complex_request():
    analyzer = RequestAnalyzer()

    request = Request(
        user_input="Analyze and debug this project step by step"
    )

    result = analyzer.analyze(request)

    assert result.complexity == "complex"


def test_analyzer_preserves_request_id():
    analyzer = RequestAnalyzer()

    request = Request(user_input="Hello ECHO")
    request_id = request.request_id

    result = analyzer.analyze(request)

    assert result.request_id == request_id