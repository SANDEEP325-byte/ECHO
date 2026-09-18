from __future__ import annotations

from packages.interfaces.pending_action import (
    ConfirmationResult,
    PendingAction,
)
from packages.interfaces.request import Request, RequestStatus
from services.brain.context_builder import context_builder
from services.brain.execution import execution_engine
from services.brain.gateway import ai_gateway
from services.brain.intent_router import Intent
from services.brain.planner import planner
from services.brain.reasoning import reasoning_engine
from services.brain.request_analyzer import request_analyzer
from services.brain.response_generator import ResponseGenerator, response_generator
from services.brain.tool_router import tool_router
from services.brain.tool_selector import tool_selector
from services.brain.verification import verification_engine
from services.logging.logger import logger
from services.memory.conversation import Message
from services.memory.facts import fact_memory
from services.memory.manager import memory_manager
from services.memory.persistent import persistent_memory


class ECHOBrain:
    """Central coordinator for ECHO's cognitive reasoning, planning, and execution.

    Orchestrates the cognitive cycle:
    Think (ReasoningEngine) → Remember (ContextBuilder) → Plan (Planner) → Act (ExecutionEngine) → Verify (VerificationEngine)
    """

    def __init__(
        self,
        memory_manager=None,
    ) -> None:
        self.memory_manager = memory_manager

    @staticmethod
    def _clean_memory_value(value: str) -> str:
        return ResponseGenerator._clean_memory_value(value)

    @staticmethod
    def _save_memory(
        user_message: str,
        memory_manager=None,
    ) -> str | None:
        mgr = memory_manager if memory_manager is not None else fact_memory
        return response_generator.generate_memory_save_response(
            user_message,
            memory_manager=mgr,
        )

    @staticmethod
    def _recall_memory(
        user_message: str,
        memory_manager=None,
    ) -> str:
        mgr = memory_manager if memory_manager is not None else fact_memory
        return response_generator.generate_memory_recall_response(
            user_message,
            memory_manager=mgr,
        )

    @staticmethod
    def _delete_memory(
        user_message: str,
        memory_manager=None,
    ) -> str:
        mgr = memory_manager if memory_manager is not None else fact_memory
        return response_generator.generate_memory_delete_response(
            user_message,
            memory_manager=mgr,
        )

    @staticmethod
    def _fixed_response(
        intent: Intent,
        memory_manager=None,
    ) -> str | None:
        mgr = memory_manager if memory_manager is not None else fact_memory
        return response_generator.generate_fixed_response(
            intent,
            memory_manager=mgr,
        )

    @staticmethod
    def _execute_tool_for_intent(
        intent: Intent,
        user_message: str,
    ) -> str | None:
        tool_name = tool_router.get_tool_for_intent(intent.value)

        if tool_name is None:
            return None

        result = tool_router.execute_for_intent(
            intent.value,
            user_message,
        )

        logger.info(
            "Brain received {} tool result: {}",
            tool_name,
            result,
        )

        return str(result)

    async def process(self, user_message: str | Request) -> str:
        if isinstance(user_message, Request):
            request = user_message
            msg_text = request.user_input
        else:
            msg_text = user_message
            request = Request(
                user_input=msg_text,
            )

        logger.info("Brain processing request")

        trimmed = msg_text.strip()
        if trimmed.startswith("/confirm "):
            target_id = trimmed[len("/confirm ") :].strip()
            confirm_res = self.confirm_action(target_id)
            if confirm_res.success:
                resp_text = f"Action '{target_id}' confirmed and executed successfully: {confirm_res.result}"
            else:
                resp_text = f"Action confirmation failed: {confirm_res.message}"
            if self.memory_manager is not None:
                self.memory_manager.save_message(role="user", content=msg_text)
                self.memory_manager.save_message(role="assistant", content=resp_text)
            return resp_text

        if trimmed.startswith("/cancel "):
            target_id = trimmed[len("/cancel ") :].strip()
            cancel_res = self.cancel_action(target_id)
            if cancel_res.success:
                resp_text = f"Action '{target_id}' has been cancelled."
            else:
                resp_text = f"Action cancellation failed: {cancel_res.message}"
            if self.memory_manager is not None:
                self.memory_manager.save_message(role="user", content=msg_text)
                self.memory_manager.save_message(role="assistant", content=resp_text)
            return resp_text

        # 1. Analyze Request
        try:
            request = request_analyzer.analyze(request)
        except Exception as exc:
            request.status = RequestStatus.FAILED
            request.error = str(exc)
            logger.error(
                "Request analysis failed for request {}: {}",
                request.request_id,
                exc,
            )
            return response_generator.generate_fallback_response(str(exc))

        # 2. Context Building (Remember)
        try:
            if self.memory_manager is not None:
                request = context_builder.build(
                    request,
                    memory_manager=self.memory_manager,
                )
            else:
                request = context_builder.build(
                    request,
                    memory=persistent_memory,
                    facts=fact_memory,
                )
        except Exception as exc:
            request.status = RequestStatus.FAILED
            request.error = str(exc)
            logger.error(
                "Context building failed for request {}: {}",
                request.request_id,
                exc,
            )
            return response_generator.generate_fallback_response(str(exc))

        # 3. Cognitive Reasoning (Think)
        try:
            reasoning_decision = reasoning_engine.reason(
                request.user_input,
                context=request.context,
            )
        except Exception as exc:
            logger.warning(
                "Reasoning engine failed for request {}: {}",
                request.request_id,
                exc,
            )
            reasoning_decision = None

        # 4. Planning (Plan)
        requires_planning = request.complexity == "complex" or (
            reasoning_decision is not None and reasoning_decision.requires_planning
        )

        try:
            plan = planner.create_plan(
                request.user_input,
                requires_planning=requires_planning,
            )
        except Exception as exc:
            request.status = RequestStatus.FAILED
            request.error = str(exc)
            logger.error(
                "Planning failed for request {}: {}",
                request.request_id,
                exc,
            )
            return response_generator.generate_fallback_response(str(exc))

        request.plan = [
            {
                "step": step.step_number,
                "description": step.description,
            }
            for step in plan.steps
        ]

        request.status = RequestStatus.PLANNING if plan.requires_planning else request.status

        # 5. Tool Selection
        try:
            request = tool_selector.select(
                request,
                plan,
            )
        except Exception as exc:
            request.status = RequestStatus.FAILED
            request.error = str(exc)
            logger.error(
                "Tool selection failed for request {}: {}",
                request.request_id,
                exc,
            )
            return response_generator.generate_fallback_response(str(exc))

        logger.info(
            "Request {} planning complete: requires_planning={}, steps={}",
            request.request_id,
            plan.requires_planning,
            len(plan.steps),
        )

        execution_result = None
        verification_result = None
        response = None

        # 6. Execution (Act) & Verification (Verify)
        if plan.requires_planning:
            try:
                execution_result = execution_engine.execute(
                    request,
                    plan,
                )
            except Exception as exc:
                request.status = RequestStatus.FAILED
                request.error = str(exc)
                logger.error(
                    "Execution failed for request {}: {}",
                    request.request_id,
                    exc,
                )
                return response_generator.generate_fallback_response(str(exc))

            if execution_result.requires_confirmation:
                response = response_generator.generate_confirmation_prompt(
                    execution_result.pending_action
                )
                if self.memory_manager is not None:
                    self.memory_manager.save_message(role="user", content=msg_text)
                    self.memory_manager.save_message(role="assistant", content=response)
                else:
                    persistent_memory.save_message(role="user", content=msg_text)
                    persistent_memory.save_message(role="assistant", content=response)
                return response

            if not execution_result.success:
                request.status = RequestStatus.FAILED
                request.error = execution_result.error
                logger.error(
                    "Execution failed for request {}: {}",
                    request.request_id,
                    execution_result.error,
                )
                return execution_result.error

            try:
                verification_result = verification_engine.verify(
                    request,
                    execution_result,
                )
            except Exception as exc:
                request.status = RequestStatus.FAILED
                request.error = str(exc)
                logger.error(
                    "Verification failed for request {}: {}",
                    request.request_id,
                    exc,
                )
                return response_generator.generate_fallback_response(str(exc))

            if not verification_result.success:
                request.status = RequestStatus.FAILED
                request.error = verification_result.error
                logger.error(
                    "Verification failed for request {}: {}",
                    request.request_id,
                    verification_result.error,
                )
                return verification_result.error

            request.status = RequestStatus.COMPLETED
            response = execution_result.result

        # Build conversation messages for AI Gateway or context formatting
        messages = [
            Message(
                role=message["role"],
                content=message["content"],
            )
            for message in request.context["recent_messages"]
        ]

        messages.append(
            Message(
                role="user",
                content=msg_text,
            )
        )

        facts = request.context.get("facts", {})

        if facts:
            memory_lines = ["Known facts about the user:"]
            for key, value in facts.items():
                memory_lines.append(f"- {key}: {value}")

            messages.insert(
                0,
                Message(
                    role="system",
                    content="\n".join(memory_lines),
                ),
            )

        semantic_memories = request.context.get("semantic_memories", [])

        if semantic_memories:
            semantic_lines = ["Relevant context from memory:"]
            for item in semantic_memories:
                content = item.get("content") or item.get("document") or item.get("text", "")
                if content:
                    semantic_lines.append(f"- {content}")

            if len(semantic_lines) > 1:
                messages.insert(
                    0,
                    Message(
                        role="system",
                        content="\n".join(semantic_lines),
                    ),
                )

        intent = Intent(request.intent)
        logger.info("Detected intent: {}", intent.value)

        tool_name = tool_router.get_tool_for_intent(intent.value)
        if tool_name:
            logger.info("Intent mapped to tool: {}", tool_name)

        # Handle deterministic intents without invoking generative LLM
        fixed_response = self._fixed_response(
            intent,
            memory_manager=self.memory_manager,
        )
        if fixed_response is not None:
            response = fixed_response

        elif intent == Intent.MEMORY_SAVE:
            response = self._save_memory(
                msg_text,
                memory_manager=self.memory_manager,
            )

        elif intent == Intent.MEMORY_RECALL:
            response = self._recall_memory(
                msg_text,
                memory_manager=self.memory_manager,
            )

        elif intent == Intent.MEMORY_DELETE:
            response = self._delete_memory(
                msg_text,
                memory_manager=self.memory_manager,
            )

        elif response is not None:
            pass

        else:
            tool_result = self._execute_tool_for_intent(
                intent,
                msg_text,
            )

            if tool_result is not None:
                response = response_generator.generate_tool_response(
                    intent,
                    tool_result,
                )
            else:
                try:
                    response = await ai_gateway.generate(
                        messages,
                        tools=tool_router.get_available_tools(),
                    )
                except Exception as exc:
                    request.status = RequestStatus.FAILED
                    request.error = str(exc)
                    logger.error(
                        "AI Gateway failed for request {}: {}",
                        request.request_id,
                        exc,
                    )
                    return response_generator.generate_fallback_response(str(exc))

        # Persist conversation turns
        if self.memory_manager is not None:
            self.memory_manager.save_message(
                role="user",
                content=msg_text,
            )
            self.memory_manager.save_message(
                role="assistant",
                content=response,
            )
        else:
            persistent_memory.save_message(
                role="user",
                content=msg_text,
            )
            persistent_memory.save_message(
                role="assistant",
                content=response,
            )

        logger.info("Brain completed request")
        return response

    def confirm_action(self, action_id: str) -> ConfirmationResult:
        """Confirm and resume an unexpired pending action through the execution pipeline."""
        logger.info("ECHOBrain confirming action: {}", action_id)
        return execution_engine.resume_pending_action(action_id)

    def cancel_action(self, action_id: str) -> ConfirmationResult:
        """Cancel a pending action, permanently preventing execution."""
        logger.info("ECHOBrain cancelling action: {}", action_id)
        return execution_engine.cancel_pending_action(action_id)

    def get_pending_action(self, action_id: str) -> PendingAction | None:
        """Retrieve details of a pending action by its identifier."""
        return execution_engine.pending_action_manager.get_action(action_id)


echo_brain = ECHOBrain(
    memory_manager=memory_manager,
)
