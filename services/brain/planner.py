from packages.interfaces.plan import Plan, PlanStep

class Planner:
    """Creates an execution plan from an analyzed user request."""

    @staticmethod
    def create_plan(
        user_message: str,
        requires_planning: bool,
    ) -> Plan:
        if not requires_planning:
            return Plan(
                requires_planning=False,
                steps=[],
            )

        normalized = user_message.strip().lower()

        steps: list[PlanStep] = []

        if "create" in normalized and "run" in normalized:
            steps = [
                PlanStep(
                    step_number=1,
                    description="Create the requested project or resource.",
                    tool_name="terminal",
                ),
                PlanStep(
                    step_number=2,
                    description="Create or configure the required files.",
                    tool_name="terminal",
                ),
                PlanStep(
                    step_number=3,
                    description="Run the requested project or command.",
                    tool_name="terminal",
                ),
                PlanStep(
                    step_number=4,
                    description="Verify that the operation completed successfully.",
                ),
            ]
        else:
            steps = [
                PlanStep(
                    step_number=1,
                    description="Analyze and execute the requested task.",
                ),
                PlanStep(
                    step_number=2,
                    description="Verify the result.",
                ),
            ]

        return Plan(
            requires_planning=True,
            steps=steps,
        )

planner = Planner()