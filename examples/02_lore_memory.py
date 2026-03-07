"""
Example 02: Long-Term Memory with Lore
This script demonstrates how Shuru Blueprint uses Lore to automatically 
hydrate the system prompt with context from the system's long-term memory.
"""

from blueprint.parser import SpecParser
from blueprint.compiler import BlueprintCompiler
from blueprint.enforcer import SchemaEnforcer

def main():
    # 1. Load the Lore-integrated Blueprint
    spec = SpecParser.parse_yaml("demo_spec_lore.yaml")
    
    # 2. Compile - This automatically calls 'lore recall' for each query in lore_context
    print("Hydrating system prompt with Lore context...")
    system_prompt = BlueprintCompiler.compile_prompt(spec)
    ResponseModel = BlueprintCompiler.compile_schema(spec, model_name="MemorySummary")
    
    # 3. Generate a summary
    enforcer = SchemaEnforcer()
    user_query = "Summarize the latest decisions regarding database schema."
    
    result = enforcer.generate(system_prompt, user_query, ResponseModel)
    
    print(f"\n--- Lore-Augmented Summary ---\n{result.summary}")
    print(f"Decisions identified: {result.decision_count}")

if __name__ == "__main__":
    main()
"""
Note: For this to work in a real environment, the 'lore' CLI must be in 
your PATH and contain entries matching 'architectural decisions', etc.
"""
