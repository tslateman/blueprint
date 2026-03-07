"""
Example 03: Secure Execution in Shuru Vault
This script demonstrates how Shuru Blueprint handles dynamic code generation 
and execution within a Zero-Trust sandbox using the Shuru CLI.
"""

from blueprint.parser import SpecParser
from blueprint.compiler import BlueprintCompiler
from blueprint.enforcer import SchemaEnforcer
from vault.tool_router import ToolRouter

def main():
    # 1. Setup
    spec = SpecParser.parse_yaml("demo_spec.yaml")
    system_prompt = BlueprintCompiler.compile_prompt(spec)
    ResponseModel = BlueprintCompiler.compile_schema(spec, model_name="CodeExecutionResult")
    
    # 2. Ask a question requiring logic
    user_query = "Calculate exactly how many seconds are in 3 years (assuming 365 days/year)."
    enforcer = SchemaEnforcer()
    
    print(f"--- Question ---\n{user_query}\n")
    
    # 3. Get the code-containing result
    result = enforcer.generate(system_prompt, user_query, ResponseModel)
    
    script_code = getattr(result, "python_execution_script", None)
    
    if script_code:
        print(f"--- Generated Python Script ---\n{script_code}\n")
        
        # 4. Route the execution to the Shuru Sandbox (Vault)
        router = ToolRouter()
        vault_output = router.execute_python_code(script_code)
        
        print(f"--- Vault Execution Result ---\n{vault_output}")
    else:
        print("No execution script generated.")

if __name__ == "__main__":
    main()
