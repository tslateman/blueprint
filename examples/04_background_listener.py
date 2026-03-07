"""
Example 04: Background Listener Agent
This script demonstrates an "invisible" background agent that monitors 
a directory (inbox/) and automatically triggers a Shuru Blueprint 
when a new file is detected.
"""

import time
import os
import json
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from blueprint.parser import SpecParser
from blueprint.compiler import BlueprintCompiler
from blueprint.enforcer import SchemaEnforcer

INBOX_DIR = "inbox"
OUTBOX_DIR = "outbox"

class BlueprintTriggerHandler(FileSystemEventHandler):
    """Listens for new .txt files and triggers the blueprint enforcer."""
    
    def __init__(self):
        self.spec = SpecParser.parse_yaml("demo_spec.yaml")
        self.enforcer = SchemaEnforcer()
        # Pre-compile schema for performance
        self.system_prompt = BlueprintCompiler.compile_prompt(self.spec)
        self.ResponseModel = BlueprintCompiler.compile_schema(self.spec)

    def on_created(self, event):
        if event.is_directory or not event.src_path.endswith(".txt"):
            return
            
        print(f"\n[EVENT] New file detected: {event.src_path}")
        self.process_file(event.src_path)

    def process_file(self, file_path):
        try:
            # 1. Read the input
            with open(file_path, "r") as f:
                user_input = f.read().strip()
            
            if not user_input:
                print(f"[SKIP] File {file_path} is empty.")
                return

            print(f"[ACTION] Triggering blueprint for: '{user_input[:30]}...'")
            
            # 2. Run the Blueprint Engine
            result = self.enforcer.generate(self.system_prompt, user_input, self.ResponseModel)
            
            # 3. Output the result to the outbox
            output_filename = Path(file_path).stem + "_result.json"
            output_path = os.path.join(OUTBOX_DIR, output_filename)
            
            with open(output_path, "w") as f:
                f.write(result.model_dump_json(indent=2))
            
            print(f"[SUCCESS] Result written to: {output_path}")
            
            # Optional: Move the processed file to a 'done' folder
            # os.rename(file_path, os.path.join("inbox/done", Path(file_path).name))
            
        except Exception as e:
            print(f"[ERROR] Failed to process {file_path}: {e}")

def main():
    # Ensure directories exist
    os.makedirs(INBOX_DIR, exist_ok=True)
    os.makedirs(OUTBOX_DIR, exist_ok=True)
    
    event_handler = BlueprintTriggerHandler()
    observer = Observer()
    observer.schedule(event_handler, INBOX_DIR, recursive=False)
    
    print(f"--- Background Blueprint Listener Started ---")
    print(f"Monitoring '{INBOX_DIR}/' for new .txt files...")
    print(f"Results will be written to '{OUTBOX_DIR}/'...")
    print(f"Press Ctrl+C to stop.")
    
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()
