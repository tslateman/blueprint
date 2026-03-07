"""
Example 07: Meta Orchestration (The Agent Team)
This script demonstrates running multiple background agents (Extraction 
and Facade Generation) simultaneously.
"""

import time
import os
from blueprint.orchestrator import BlueprintOrchestrator

def main():
    # 1. Define our 'Agent Team'
    agent_team = [
        "demo_spec.yaml",                       # Extraction Specialist
        "blueprints/meta/facade_generator.yaml" # API Architect (Meta)
    ]
    
    # 2. Run the Orchestrator
    orchestrator = BlueprintOrchestrator(agent_team)
    orchestrator.start()
    
    print("\n--- [META ORCHESTRATION ACTIVE] ---")
    print("1. Standard Extraction: Drop .txt into 'inbox/'")
    print("2. Meta Facade Generator: Drop .txt into 'inbox/meta/'")
    print("\nPress Ctrl+C to exit.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        orchestrator.stop()

if __name__ == "__main__":
    main()
