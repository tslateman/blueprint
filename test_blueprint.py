import pytest
from blueprint.parser import SpecParser
from blueprint.compiler import BlueprintCompiler
from pydantic import BaseModel

def test_spec_parser():
    spec = SpecParser.parse_yaml("demo_spec.yaml")
    assert "intent" in spec
    assert "output_schema" in spec
    
def test_blueprint_compiler_prompt():
    spec = {
        "intent": "You are a test bot.",
        "constraints": ["Be concise."]
    }
    prompt = BlueprintCompiler.compile_prompt(spec)
    assert "You are a test bot." in prompt
    assert "Be concise." in prompt
    
def test_blueprint_compiler_schema():
    spec = {
        "output_schema": {
            "name": {"type": "string", "description": "The name"},
            "age": {"type": "integer", "description": "The age"}
        }
    }
    ModelClass = BlueprintCompiler.compile_schema(spec, model_name="TestModel")
    assert issubclass(ModelClass, BaseModel)
    
    # Check if instance can be created
    instance = ModelClass(name="Alice", age=30)
    assert instance.name == "Alice"
    assert instance.age == 30
