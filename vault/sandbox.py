import subprocess
import tempfile
import json
import os
from pathlib import Path
from typing import Dict, Tuple

class SandboxError(Exception):
    pass

class ShuruSandbox:
    """A Zero-Trust Execution Vault using shuru.run."""
    
    def __init__(self, cpus: int = 2, memory: int = 1024, allow_net: bool = False):
        self.cpus = cpus
        self.memory = memory
        self.allow_net = allow_net
        
    def execute(self, command: str, files: Dict[str, str] = None) -> Tuple[str, str, int]:
        """
        Executes a command inside the shuru sandbox.
        Optionally mounts a temporary directory containing 'files'.
        
        Args:
            command: The command to run in the sandbox container natively.
            files: Dictionary mapping of filename to file content.
            
        Returns:
            Tuple of (stdout, stderr, exit_code)
        """
        
        # Build base shuru command
        shuru_cmd = [
            "shuru", "run", 
            "--cpus", str(self.cpus), 
            "--memory", str(self.memory)
        ]
        
        if self.allow_net:
            shuru_cmd.append("--allow-net")
            
        # Context block to handle temporary directory if files are provided
        if files:
            with tempfile.TemporaryDirectory() as temp_dir:
                # Write files
                for filename, content in files.items():
                    path = Path(temp_dir) / filename
                    # Ensure subdirectories exist
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content)
                
                # Mount directory into shuru
                shuru_cmd.extend(["--mount", f"{temp_dir}:/workspace"])
                
                # Append the final command wrapped in sh to handle complex spacing or pipes safely
                shuru_cmd.extend(["--", "sh", "-c", f"cd /workspace && {command}"])
                return self._run_subprocess(shuru_cmd)
        else:
            shuru_cmd.extend(["--", "sh", "-c", command])
            return self._run_subprocess(shuru_cmd)
            
    def _run_subprocess(self, cmd: list) -> Tuple[str, str, int]:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False
            )
            return result.stdout, result.stderr, result.returncode
        except FileNotFoundError:
            raise SandboxError("shuru CLI not found. Is it installed and in your PATH?")
