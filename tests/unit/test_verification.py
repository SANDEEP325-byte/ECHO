from packages.interfaces.request import Request, RequestStatus
from services.brain.verification import VerificationEngine
from packages.interfaces.execution import ExecutionResult
from packages.interfaces.verification import VerificationResult


def test_verification_result_represents_success():
    result = VerificationResult(
        success=True,
        result="verified",
    )

    assert result.success is True
    assert result.result == "verified"
    assert result.error is None


def test_verification_result_represents_failure():
    result = VerificationResult(
        success=False,
        error="Verification failed",
    )

    assert result.success is False
    assert result.result is None
    assert result.error == "Verification failed"


def test_verification_result_is_immutable():
    result = VerificationResult(
        success=True,
        result="verified",
    )

    try:
        result.success = False
        assert False
    except AttributeError:
        assert True
        
def test_verification_marks_successful_request_as_verified():
    engine = VerificationEngine()

    request = Request(
        user_input="Calculate 10 + 5",
    )

    execution_result = ExecutionResult(
        success=True,
        result="15",
    )

    result = engine.verify(
        request,
        execution_result,
    )
    
    assert isinstance(result, VerificationResult)
    assert result.success is True
    assert result.result == "15"
    assert result.error is None
    assert request.status == RequestStatus.VERIFYING


def test_verification_fails_when_execution_failed():
    engine = VerificationEngine()

    request = Request(
        user_input="Run a task",
    )

    execution_result = ExecutionResult(
        success=False,
        error="Tool execution failed",
    )

    result = engine.verify(
        request,
        execution_result,
    )

    assert isinstance(result, VerificationResult)
    assert result.success is False
    assert result.error == "Tool execution failed"
    assert request.status == RequestStatus.FAILED


def test_verification_preserves_request_id():
    engine = VerificationEngine()

    request = Request(
        user_input="Calculate 10 + 5",
    )

    request_id = request.request_id

    execution_result = ExecutionResult(
        success=True,
        result="15",
    )

    engine.verify(
        request,
        execution_result,
    )

    assert request.request_id == request_id
    
def test_verification_fails_when_request_has_error():
    engine = VerificationEngine()

    request = Request(
        user_input="Calculate 10 + 5",
    )

    request.error = "Previous processing failed."

    execution_result = ExecutionResult(
        success=True,
        result=15,
    )

    result = engine.verify(
        request,
        execution_result,
    )

    assert result.success is False
    assert result.error == "Previous processing failed."
    assert request.status == RequestStatus.FAILED


def test_verification_fails_when_execution_has_no_error_message():
    engine = VerificationEngine()

    request = Request(
        user_input="Calculate 10 + 5",
    )

    execution_result = ExecutionResult(
        success=False,
        error=None,
    )

    result = engine.verify(
        request,
        execution_result,
    )

    assert result.success is False
    assert result.error == (
        "Verification failed: execution was unsuccessful."
    )
    assert request.status == RequestStatus.FAILED


def test_verification_fails_when_execution_result_is_none():
    engine = VerificationEngine()

    request = Request(
        user_input="Calculate 10 + 5",
    )

    execution_result = ExecutionResult(
        success=True,
        result=None,
    )

    result = engine.verify(
        request,
        execution_result,
    )

    assert result.success is False
    assert result.error == (
        "Verification failed: execution produced no result."
    )
    assert request.status == RequestStatus.FAILED


def test_verification_stores_execution_error_on_request():
    engine = VerificationEngine()

    request = Request(
        user_input="Run a task",
    )

    execution_result = ExecutionResult(
        success=False,
        error="Permission denied.",
    )

    engine.verify(
        request,
        execution_result,
    )

    assert request.error == "Permission denied."


def test_verification_does_not_overwrite_existing_request_error():
    engine = VerificationEngine()

    request = Request(
        user_input="Run a task",
    )

    request.error = "Original request error."

    execution_result = ExecutionResult(
        success=False,
        error="Execution failed.",
    )

    result = engine.verify(
        request,
        execution_result,
    )

    assert result.error == "Original request error."
    assert request.error == "Original request error."


def test_verification_accepts_zero_as_valid_result():
    engine = VerificationEngine()

    request = Request(
        user_input="Calculate 0",
    )

    execution_result = ExecutionResult(
        success=True,
        result=0,
    )

    result = engine.verify(
        request,
        execution_result,
    )

    assert result.success is True
    assert result.result == 0
    assert request.status == RequestStatus.VERIFYING