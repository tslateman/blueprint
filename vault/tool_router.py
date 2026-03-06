import subprocess
from typing import Any, Dict, Optional
from vault.sandbox import ShuruSandbox

class ToolRouter:
    """Routes capability requests from the Blueprint Engine to the Execution Vault."""
    
    def __init__(self, sandbox_kwargs: Optional[Dict[str, Any]] = None):
        if sandbox_kwargs is None:
            sandbox_kwargs = {}
        self.sandbox = ShuruSandbox(**sandbox_kwargs)
        
    def execute_python_code(self, code_string: str, network: bool = False) -> str:
        """Helper to run a temporary Python script safely in the vault."""
        # Force temporary sandbox config override
        original_net = self.sandbox.allow_net
        # Network must be enabled to install apk packages
        self.sandbox.allow_net = network
        
        files = {"script.py": code_string}
        # Install python3 quietly, then run the script
        command = "apk add --no-cache python3 > /dev/null && python3 script.py"
        stdout, stderr, exit_code = self.sandbox.execute(command, files=files)
        
        # Restore configuration
        self.sandbox.allow_net = original_net
        
        if exit_code != 0:
            return f"Error ({exit_code}):\n{stderr}\nStdout:\n{stdout}"
        return stdout

    # --- Lore Integrations ---
    
    def lore_search(self, query: str) -> str:
        """Queries Lore for relevant context."""
        try:
            # We use '--brief' or just default recall. Let's use recall for full context mapping
            # but limit output length to avoid blowing up context windows if necessary.
            result = subprocess.run(
                ["lore", "recall", query],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode != 0:
                return f"Lore search failed: {result.stderr}"
            return result.stdout.strip()
        except FileNotFoundError:
            return "Lore CLI not found. Is it installed and in your PATH?"

    def lore_record_decision(self, decision: str, rationale: str) -> str:
        """Records a decision into Lore's journal with its rationale."""
        cmd = ["lore", "remember", decision, "--rationale", rationale]
            
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode != 0:
                return f"Lore record failed: {result.stderr}"
            return result.stdout.strip()
        except FileNotFoundError:
            return "Lore CLI not found. Is it installed and in your PATH?"
