from packages.interfaces.execution import ExecutionResult
from packages.interfaces.request import Request, RequestStatus
from packages.interfaces.verification import VerificationResult
from services.logging.logger import logger

class VerificationEngine:
    """Verifies whether an ECHO request can be considered complete."""

    def verify(
        self,
        request: Request,
        execution_result: ExecutionResult,
    ) -> VerificationResult:
        logger.info(
            "Starting verification for request {}",
            request.request_id,
        )

        request.status = RequestStatus.VERIFYING

        if request.error is not None:
            request.status = RequestStatus.FAILED

            logger.error(
                "Verification failed for request {}: {}",
                request.request_id,
                request.error,
            )

            return VerificationResult(
                success=False,
                error=request.error,
            )

        if not execution_result.success:
            request.status = RequestStatus.FAILED

            error = (
                execution_result.error
                or "Verification failed: execution was unsuccessful."
            )

            request.error = error

            logger.error(
                "Verification failed for request {}: {}",
                request.request_id,
                error,
            )

            return VerificationResult(
                success=False,
                error=error,
            )

        if execution_result.result is None:
            request.status = RequestStatus.FAILED

            error = (
                "Verification failed: "
                "execution produced no result."
            )

            request.error = error

            logger.error(
                "Verification failed for request {}: execution produced no result",
                request.request_id,
            )

            return VerificationResult(
                success=False,
                error=error,
            )

        logger.info(
            "Verification completed successfully for request {}",
            request.request_id,
        )

        return VerificationResult(
            success=True,
            result=execution_result.result,
        )

verification_engine = VerificationEngine()