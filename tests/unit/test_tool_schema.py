from packages.interfaces.tool_schema import (
    ToolDefinition,
    ToolParameter,
)


def test_tool_parameter_stores_values():
    parameter = ToolParameter(
        name="expression",
        type="string",
        description="A mathematical expression.",
        required=True,
    )

    assert parameter.name == "expression"
    assert parameter.type == "string"
    assert parameter.description == "A mathematical expression."
    assert parameter.required is True


def test_tool_parameter_required_defaults_to_true():
    parameter = ToolParameter(
        name="expression",
        type="string",
        description="A mathematical expression.",
    )

    assert parameter.required is True


def test_tool_definition_stores_values():
    definition = ToolDefinition(
        name="calculator",
        description="Performs calculations.",
    )

    assert definition.name == "calculator"
    assert definition.description == "Performs calculations."
    assert definition.parameters == ()


def test_tool_definition_stores_parameters():
    parameter = ToolParameter(
        name="expression",
        type="string",
        description="A mathematical expression.",
    )

    definition = ToolDefinition(
        name="calculator",
        description="Performs calculations.",
        parameters=(parameter,),
    )

    assert len(definition.parameters) == 1
    assert definition.parameters[0] == parameter


def test_tool_definition_to_dict():
    parameter = ToolParameter(
        name="expression",
        type="string",
        description="A mathematical expression.",
        required=True,
    )

    definition = ToolDefinition(
        name="calculator",
        description="Performs calculations.",
        parameters=(parameter,),
    )

    result = definition.to_dict()

    assert result == {
        "name": "calculator",
        "description": "Performs calculations.",
        "parameters": [
            {
                "name": "expression",
                "type": "string",
                "description": "A mathematical expression.",
                "required": True,
            }
        ],
    }


def test_tool_parameter_is_immutable():
    parameter = ToolParameter(
        name="expression",
        type="string",
        description="A mathematical expression.",
    )

    try:
        parameter.name = "changed"
        assert False
    except AttributeError:
        pass


def test_tool_definition_is_immutable():
    definition = ToolDefinition(
        name="calculator",
        description="Performs calculations.",
    )

    try:
        definition.name = "changed"
        assert False
    except AttributeError:
        pass
    
def test_tool_parameter_rejects_empty_name():
    try:
        ToolParameter(
            name="",
            type="string",
            description="A parameter.",
        )
        assert False
    except ValueError:
        pass
    
def test_tool_parameter_rejects_empty_type():
    try:
        ToolParameter(
            name="expression",
            type="",
            description="A mathematical expression.",
        )
        assert False
    except ValueError:
        pass
    
def test_tool_parameter_rejects_empty_description():
    try:
        ToolParameter(
            name="expression",
            type="string",
            description="",
        )
        assert False
    except ValueError:
        pass
    
def test_tool_definition_rejects_empty_name():
    try:
        ToolDefinition(
            name="",
            description="A tool.",
        )
        assert False
    except ValueError:
        pass
    
def test_tool_definition_rejects_empty_description():
    try:
        ToolDefinition(
            name="calculator",
            description="",
        )
        assert False
    except ValueError:
        pass
    
def test_tool_definition_rejects_invalid_parameter():
    try:
        ToolDefinition(
            name="calculator",
            description="Performs calculations.",
            parameters=("invalid",),
        )
        assert False
    except TypeError:
        pass
    
def test_tool_definition_rejects_non_tuple_parameters():
    try:
        ToolDefinition(
            name="calculator",
            description="Performs calculations.",
            parameters=[],
        )
        assert False
    except TypeError:
        pass
    
def test_tool_parameter_rejects_non_boolean_required():
    try:
        ToolParameter(
            name="expression",
            type="string",
            description="A mathematical expression.",
            required="yes",
        )
        assert False
    except TypeError:
        pass
    
def test_tool_parameter_rejects_unsupported_type():
    try:
        ToolParameter(
            name="expression",
            type="unsupported",
            description="A mathematical expression.",
        )
        assert False
    except ValueError:
        pass
    
def test_tool_parameter_normalizes_type():
    parameter = ToolParameter(
        name="age",
        type=" INTEGER ",
        description="Age of the user.",
    )

    assert parameter.type == "integer"
    
def test_tool_definition_normalizes_name_and_description():
    definition = ToolDefinition(
        name="  calculator  ",
        description="  Performs calculations.  ",
    )

    assert definition.name == "calculator"
    assert definition.description == "Performs calculations."