"""
Example 06: Background Orchestrator Demo
This script demonstrates how the BlueprintOrchestrator can automatically 
start listeners based on the 'triggers' defined in your Blueprints.
"""

import time
from blueprint.orchestrator import BlueprintOrchestrator

def main():
    # 1. Define the blueprints we want to orchestrate
    # This one has a 'file' trigger in it!
    blueprints = ["demo_spec.yaml"]
    
    # 2. Start the Orchestrator
    orchestrator = BlueprintOrchestrator(blueprints)
    orchestrator.start()
    
    print("\n--- [ORCHESTRATION ACTIVE] ---")
    print("Drop a .txt file into 'inbox/' to see the blueprint trigger.")
    print("The orchestrator is using the 'triggers' config directly from demo_spec.yaml.")
    print("Press Ctrl+C to exit.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping Orchestrator...")
        orchestrator.stop()

if __name__ == "__main__":
    main()
