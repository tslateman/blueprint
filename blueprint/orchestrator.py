"""
Blueprint Orchestrator
Listens for events defined in Blueprints and triggers executions.
"""

import time
import os
from pathlib import Path
from typing import Dict, Any, List
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from blueprint.parser import SpecParser
from blueprint.compiler import BlueprintCompiler
from blueprint.enforcer import SchemaEnforcer

class BlueprintFileSystemHandler(FileSystemEventHandler):
    """Specific handler for file-based triggers in a Blueprint."""
    
    def __init__(self, spec: Dict[str, Any], trigger_config: Dict[str, Any]):
        self.spec = spec
        self.trigger_config = trigger_config
        self.path = trigger_config.get('path', 'inbox')
        self.extension = trigger_config.get('extension', '.txt')
        self.outbox = trigger_config.get('outbox', 'outbox')
        
        # Pre-initialize enforcer and models
        self.enforcer = SchemaEnforcer(use_cli=(os.environ.get("USE_GEMINI_CLI", "").lower() == "true"))
        self.system_prompt = BlueprintCompiler.compile_prompt(self.spec)
        self.ResponseModel = BlueprintCompiler.compile_schema(self.spec)
        
        os.makedirs(self.path, exist_ok=True)
        os.makedirs(self.outbox, exist_ok=True)

    def on_created(self, event):
        if event.is_directory or not event.src_path.endswith(self.extension):
            return
            
        print(f"[ORCHESTRATOR] Event Triggered: {event.src_path}")
        self.process_event(event.src_path)

    def process_event(self, file_path):
        try:
            with open(file_path, "r") as f:
                user_input = f.read().strip()
            
            if not user_input:
                return

            result = self.enforcer.generate(self.system_prompt, user_input, self.ResponseModel)
            
            output_filename = Path(file_path).stem + "_result.json"
            output_path = os.path.join(self.outbox, output_filename)
            
            with open(output_path, "w") as f:
                f.write(result.model_dump_json(indent=2))
            
            print(f"[SUCCESS] Result written to: {output_path}")
        except Exception as e:
            print(f"[ERROR] Orchestration failed for {file_path}: {e}")

class BlueprintOrchestrator:
    """Orchestrates background listeners based on Blueprint specs."""
    
    def __init__(self, blueprint_paths: List[str]):
        self.blueprint_paths = blueprint_paths
        self.observer = Observer()
        self._handlers = []

    def start(self):
        """Analyzes blueprints and starts the appropriate observers."""
        for path in self.blueprint_paths:
            spec = SpecParser.parse_yaml(path)
            for trigger in spec.get('triggers', []):
                t_type = trigger.get('type')
                
                if t_type == 'file':
                    print(f"[INIT] Setting up file-system trigger for {path}...")
                    handler = BlueprintFileSystemHandler(spec, trigger)
                    self.observer.schedule(handler, handler.path, recursive=False)
                    self._handlers.append(handler)
                else:
                    print(f"[WARN] Unknown trigger type '{t_type}' in {path}")
                    
        if self._handlers:
            self.observer.start()
            print(f"[READY] Background Orchestrator running with {len(self._handlers)} listeners.")
        else:
            print("[INFO] No active triggers found in blueprints.")

    def stop(self):
        self.observer.stop()
        self.observer.join()
