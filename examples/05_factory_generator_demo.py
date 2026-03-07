"""
Example 05: Plan Entitlements Factory Generator (Phase 1 Demo)
This script demonstrates generating a 'Plan.FeatureEntitlement' factory 
from a simulated 'Golden Image' JSON file.
"""

import json
from blueprint.parser import SpecParser
from blueprint.compiler import BlueprintCompiler
from blueprint.enforcer import SchemaEnforcer

def main():
    # 1. Load the Factory Generator Blueprint
    spec_path = "blueprints/factory_generator/plan_entitlements.yaml"
    spec = SpecParser.parse_yaml(spec_path)
    
    # 2. Compile - This would hydrate Lore standards if present
    print(f"Compiling Blueprint: {spec_path}...")
    system_prompt = BlueprintCompiler.compile_prompt(spec)
    ResponseModel = BlueprintCompiler.compile_schema(spec, model_name="FactoryGenerationResult")
    
    # 3. Simulate a 'Golden Image' from production (obfuscated S3 JSON)
    golden_image_json = {
        "tier": "PREMIUM",
        "customer_context": "Global Enterprise Account (Marriott)",
        "features": {
            "api_access": True,
            "max_api_calls_per_month": 100000,
            "max_users": 50,
            "support_priority": "high"
        },
        "promotion_applied": "2026_spring_boost (+5000 API calls)"
    }
    
    user_prompt = f"### GOLDEN IMAGE INPUT (S3):\n{json.dumps(golden_image_json, indent=2)}\n\nPlease generate the 'FeatureEntitlement' factory."

    # 4. Enforce the Generation
    print("Generating 'Plan.FeatureEntitlement' factory via Blueprint Engine...")
    enforcer = SchemaEnforcer()
    result = enforcer.generate(system_prompt, user_prompt, ResponseModel)
    
    # 5. Output the result
    print(f"\n--- [RESULT] Factory for Tier: {result.tier_id} ---")
    print(f"Realism Score: {result.realism_score}%")
    print(f"Active: {result.is_active}")
    print(f"Max API Calls: {result.max_api_calls}")
    print("\n--- [GENERATED CODE] ---")
    print(result.python_factory_code)

if __name__ == "__main__":
    main()
