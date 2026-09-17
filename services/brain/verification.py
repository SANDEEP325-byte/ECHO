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

        # Filesystem post-condition state verification
        items_to_verify = (
            execution_result.result
            if isinstance(execution_result.result, list)
            else [execution_result.result]
        )

        for item in items_to_verify:
            if isinstance(item, dict) and "operation" in item:
                fs_error = self._verify_filesystem_postcondition(item)
                if fs_error is not None:
                    request.status = RequestStatus.FAILED
                    request.error = fs_error
                    logger.error(
                        "Verification failed for request {}: {}",
                        request.request_id,
                        fs_error,
                    )
                    return VerificationResult(
                        success=False,
                        error=fs_error,
                    )

        logger.info(
            "Verification completed successfully for request {}",
            request.request_id,
        )

        return VerificationResult(
            success=True,
            result=execution_result.result,
        )

    def _verify_filesystem_postcondition(self, meta: dict) -> str | None:
        """Verify that filesystem state reflects the executed operation."""
        from pathlib import Path

        op = meta.get("operation")
        try:
            if op == "create_file":
                target = Path(meta["path"])
                if not target.is_file():
                    return f"Verification failed: created file '{target}' does not exist."

            elif op == "create_folder":
                target = Path(meta["path"])
                if not target.is_dir():
                    return f"Verification failed: created directory '{target}' does not exist."

            elif op == "copy_file":
                dst = Path(meta["destination"])
                if not dst.exists():
                    return f"Verification failed: copied destination '{dst}' does not exist."

            elif op in {"rename_file", "move_file"}:
                src = Path(meta["source"])
                dst = Path(meta["destination"])
                if not dst.exists():
                    return f"Verification failed: destination '{dst}' does not exist."
                if src.resolve() != dst.resolve() and src.exists():
                    return f"Verification failed: source '{src}' still exists after move."

            elif op == "delete_file":
                target = Path(meta["path"])
                if target.exists():
                    return f"Verification failed: deleted target '{target}' still exists."

            elif op == "open_file":
                target = Path(meta["path"])
                if not target.is_file():
                    return f"Verification failed: target file '{target}' does not exist."
                if not meta.get("verified"):
                    return "Verification failed: open_file operation was not verified."

            elif op == "open_folder":
                target = Path(meta["path"])
                if not target.is_dir():
                    return f"Verification failed: target directory '{target}' does not exist."
                if not meta.get("verified"):
                    return "Verification failed: open_folder operation was not verified."

            elif op == "open_application":
                target = Path(meta["path"])
                if not target.is_file():
                    return f"Verification failed: application executable '{target}' does not exist."
                if not meta.get("verified"):
                    return "Verification failed: open_application operation was not verified."

            elif op in ("execute_command", "run_command"):
                if meta.get("timed_out"):
                    return "Verification failed: command execution timed out."
                if meta.get("status") == "failed" and meta.get("exit_code") is None:
                    return "Verification failed: process execution failed without exit code."
                if not meta.get("verified"):
                    return "Verification failed: command operation was not verified."
        except Exception as exc:
            return f"Verification failed during filesystem check: {exc}"

        return None

verification_engine = VerificationEngine()