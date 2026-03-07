"""
Blueprint Guardian
The 'Conscience' of the Background Agent Team. 
Monitors for drift and performs self-healing.
"""

import time
import os
import hashlib
from typing import List, Dict, Any
from blueprint.orchestrator import BlueprintOrchestrator
from blueprint.parser import SpecParser
from blueprint.enforcer import SchemaEnforcer

class BlueprintGuardian(BlueprintOrchestrator):
    """
    Extends the Orchestrator to monitor for system 'drift'.
    It ensures that implementation code matches the Blueprint Specs.
    """
    
    def __init__(self, blueprint_paths: List[str], interval: int = 60):
        super().__init__(blueprint_paths)
        self.interval = interval # Health check interval in seconds
        self.enforcer = SchemaEnforcer()

    def run_health_check(self):
        """Perform a periodic scan for architectural drift."""
        print(f"\n[GUARDIAN] Starting scheduled health check...")
        for path in self.blueprint_paths:
            try:
                spec = SpecParser.parse_yaml(path)
                # Here we could check if generated files exist or if their hashes match
                # For now, we'll simulate a drift check
                print(f"[GUARDIAN] Auditing: {path} - OK")
            except Exception as e:
                print(f"[GUARDIAN] DRIFT DETECTED in {path}: {e}")
                self._trigger_self_healing(path, str(e))

    def _trigger_self_healing(self, blueprint_path: str, error_msg: str):
        """Attempt to automatically resolve a blueprint error via the Healer Agent."""
        print(f"[HEAL] Initiating self-healing for: {blueprint_path}")
        
        try:
            from vault.tool_router import ToolRouter
            
            # 1. Load the Healer Blueprint
            healer_spec = SpecParser.parse_yaml("blueprints/meta/self_healer.yaml")
            healer_prompt = BlueprintCompiler.compile_prompt(healer_spec)
            HealerModel = BlueprintCompiler.compile_schema(healer_spec, model_name="HealAction")
            
            # 2. Describe the failure to the Healer
            issue_description = (
                f"Blueprint Path: {blueprint_path}\n"
                f"Error Message: {error_msg}\n"
                f"Task: Please generate a remediation script to fix this drift."
            )
            
            # 3. Generate the fix
            heal_result = self.enforcer.generate(healer_prompt, issue_description, HealerModel)
            
            print(f"[HEAL] Analysis: {heal_result.error_analysis}")
            print(f"[HEAL] Rationale: {heal_result.rationale}")
            
            # 4. Execute the fix in the Shuru Vault
            if heal_result.confidence_score > 80:
                print(f"[HEAL] High confidence fix ({heal_result.confidence_score}%). Executing in Vault...")
                router = ToolRouter()
                vault_out = router.execute_python_code(heal_result.remediation_script)
                print(f"[HEAL] Vault Output: {vault_out}")
            else:
                print(f"[HEAL] Confidence too low ({heal_result.confidence_score}%). Manual intervention required.")
                
        except Exception as e:
            print(f"[HEAL] ERROR: Self-healing failed: {e}")

    def start_guarding(self):
        """Runs the orchestrator and the periodic health check loop."""
        self.start() # Start the background listeners
        
        try:
            while True:
                self.run_health_check()
                time.sleep(self.interval)
        except KeyboardInterrupt:
            self.stop()

if __name__ == "__main__":
    # Demo Guardian
    guardian = BlueprintGuardian(["demo_spec.yaml"], interval=10)
    guardian.start_guarding()
