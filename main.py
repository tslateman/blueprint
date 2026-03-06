import os
import json
from dotenv import load_dotenv
from blueprint.parser import SpecParser
from blueprint.compiler import BlueprintCompiler
from blueprint.enforcer import SchemaEnforcer
from vault.tool_router import ToolRouter

load_dotenv()


def main():
    # 1. Parse the Spec
    # Use the original spec the user modified
    spec_path = "demo_spec.yaml"
    print(f"Loading spec from {spec_path}...")
    spec = SpecParser.parse_yaml(spec_path)

    # 2. Compile System Prompt and Output Schema
    print("Compiling system prompt and dynamic schema...")
    system_prompt = BlueprintCompiler.compile_prompt(spec)
    ResponseModel = BlueprintCompiler.compile_schema(spec, model_name="DemoOutput")

    # 3. Simulate User Input
    user_input = "I recently visited Paris with John Doe. It was absolutely stunning, though quite busy near the Eiffel Tower. Also, how many hours are in 3 weeks? Write a script to calculate this exactly and print the result."

    # 4. Enforce the Output
    # Ensure OPENAI_API_KEY or GEMINI_API_KEY is available in the environment when testing this!
    print("Enforcing blueprint intent with LLM...")
    if not os.environ.get("OPENAI_API_KEY") and not os.environ.get("GEMINI_API_KEY"):
         print("WARNING: Neither OPENAI_API_KEY nor GEMINI_API_KEY is set. The LLM call will fail. Set one and try again.")
         return

    enforcer = SchemaEnforcer()
    result = enforcer.generate(system_prompt, user_input, ResponseModel)

    # 5. Output Result
    print("\n=== Result Validated by Blueprint Engine ===")
    print(result.model_dump_json(indent=2))

    # 6. Execute Sandbox Code
    # The output_schema in demo_spec handles python_execution_script as an optional string.
    script_code = getattr(result, "python_execution_script", None)
    if script_code:
        print("\n=== Executing Generated Code in Shuru Vault ===")
        router = ToolRouter()
        print(f"Executing Script:\n{script_code}\n")
        
        # We need to wrap in try/except or just let it run
        vault_output = router.execute_python_code(script_code)
        print(f"\n--- Vault Execution Result ---\n{vault_output}")
    else:
        print("\n=== No Python Script Generated ===")

if __name__ == "__main__":
    main()
