"""
Example 01: Basic Entity Extraction
This script demonstrates how to use a Blueprint to extract structured 
entities from raw text using the demo_spec.yaml blueprint.
"""

from blueprint.parser import SpecParser
from blueprint.compiler import BlueprintCompiler
from blueprint.enforcer import SchemaEnforcer

def main():
    # 1. Load and Parse the Blueprint
    spec = SpecParser.parse_yaml("demo_spec.yaml")
    
    # 2. Compile into a Prompt and a Pydantic Model
    system_prompt = BlueprintCompiler.compile_prompt(spec)
    ResponseModel = BlueprintCompiler.compile_schema(spec, model_name="ExtractionResult")
    
    # 3. Use the Enforcer to generate a structured result
    enforcer = SchemaEnforcer()
    user_input = "I'm Sarah and I just visited the Eiffel Tower in Paris."
    
    print(f"--- User Input ---\n{user_input}\n")
    
    result = enforcer.generate(system_prompt, user_input, ResponseModel)
    
    # 4. Access the validated data directly
    print("--- Extracted Entities ---")
    print(f"Target Name: {result.target_name}")
    print(f"Locations:   {', '.join(result.locations)}")
    print(f"Confidence:  {result.confidence_score}%")

if __name__ == "__main__":
    main()
