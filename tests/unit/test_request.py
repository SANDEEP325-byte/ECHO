from packages.interfaces.request import Request, RequestStatus


def test_request_has_default_values():
    request = Request(user_input="Hello ECHO")

    assert request.user_input == "Hello ECHO"
    assert request.source == "chat"
    assert request.session_id is None
    assert request.intent is None
    assert request.priority is None
    assert request.complexity is None
    assert request.context == {}
    assert request.plan == []
    assert request.selected_tools == []
    assert request.status == RequestStatus.CREATED
    assert request.result is None
    assert request.error is None


def test_request_generates_unique_ids():
    request_one = Request(user_input="Hello")
    request_two = Request(user_input="Hello")

    assert request_one.request_id != request_two.request_id


def test_request_accepts_custom_values():
    request = Request(
        user_input="Open Chrome",
        source="api",
        session_id="session-123",
        intent="automation",
        priority="high",
        complexity="simple",
    )

    assert request.source == "api"
    assert request.session_id == "session-123"
    assert request.intent == "automation"
    assert request.priority == "high"
    assert request.complexity == "simple"


def test_request_status_can_change():
    request = Request(user_input="Run a task")

    request.status = RequestStatus.ANALYZING

    assert request.status == RequestStatus.ANALYZING


def test_request_can_store_plan_and_tools():
    request = Request(user_input="Install a package")

    request.plan = [
        {"step": 1, "action": "check_environment"},
        {"step": 2, "action": "install_package"},
    ]

    request.selected_tools = ["terminal"]

    assert len(request.plan) == 2
    assert request.selected_tools == ["terminal"]


def test_request_can_store_result_and_error():
    request = Request(user_input="Run command")

    request.result = "success"

    assert request.result == "success"

    request.status = RequestStatus.FAILED
    request.error = "Permission denied"

    assert request.status == RequestStatus.FAILED
    assert request.error == "Permission denied"