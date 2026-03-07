"""
Example 08: Self-Healing Demo
This script demonstrates how the Blueprint Guardian detects architectural drift
(e.g., a missing blueprint file) and triggers the Self-Healing agent to fix it.
"""

import time
import os
from blueprint.guardian import BlueprintGuardian

def main():
    # 1. Point the Guardian at a non-existent blueprint to trigger drift
    missing_blueprint = "blueprints/MISSING_ESSENTIAL_SPEC.yaml"
    
    # Ensure it's actually missing
    if os.path.exists(missing_blueprint):
        os.remove(missing_blueprint)
        
    print(f"--- [SELF-HEALING DEMO STARTED] ---")
    print(f"Goal: Watch the Guardian detect the missing file: '{missing_blueprint}' and attempt a fix.")
    
    # 2. Start the Guardian with a short interval
    guardian = BlueprintGuardian([missing_blueprint], interval=5)
    
    # Run one manual check for the demo
    guardian.run_health_check()
    
    print("\n[INFO] Demo complete. In a production scenario, the Guardian would run this loop indefinitely.")

if __name__ == "__main__":
    main()
