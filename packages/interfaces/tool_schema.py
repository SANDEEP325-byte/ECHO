from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = True

    _SUPPORTED_TYPES = {
        "string",
        "integer",
        "number",
        "boolean",
    }

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        normalized_type = self.type.strip().lower()
        normalized_description = self.description.strip()

        if not normalized_name:
            raise ValueError(
                "Tool parameter name cannot be empty."
            )

        if not normalized_type:
            raise ValueError(
                "Tool parameter type cannot be empty."
            )

        if normalized_type not in self._SUPPORTED_TYPES:
            raise ValueError(
                f"Unsupported tool parameter type: {self.type}"
            )

        if not normalized_description:
            raise ValueError(
                "Tool parameter description cannot be empty."
            )

        if not isinstance(self.required, bool):
            raise TypeError(
                "Tool parameter required must be a boolean."
            )

        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "type", normalized_type)
        object.__setattr__(
            self,
            "description",
            normalized_description,
        )


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: tuple[ToolParameter, ...] = ()

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        normalized_description = self.description.strip()

        if not normalized_name:
            raise ValueError(
                "Tool definition name cannot be empty."
            )

        if not normalized_description:
            raise ValueError(
                "Tool definition description cannot be empty."
            )

        if not isinstance(self.parameters, tuple):
            raise TypeError(
                "Tool definition parameters must be a tuple."
            )

        for parameter in self.parameters:
            if not isinstance(parameter, ToolParameter):
                raise TypeError(
                    "Tool definition parameters must be "
                    "ToolParameter instances."
                )

        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(
            self,
            "description",
            normalized_description,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": [
                {
                    "name": parameter.name,
                    "type": parameter.type,
                    "description": parameter.description,
                    "required": parameter.required,
                }
                for parameter in self.parameters
            ],
        }