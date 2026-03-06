import yaml
from pathlib import Path
from typing import Any, Dict

class SpecParser:
    """Parses Declarative Blueprint specifications from YAML/Markdown."""
    
    @staticmethod
    def parse_yaml(file_path: str | Path) -> Dict[str, Any]:
        """Reads a YAML spec file and returns a dictionary."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Spec file not found: {path}")
            
        with open(path, 'r', encoding='utf-8') as f:
            try:
                spec = yaml.safe_load(f)
                return spec
            except yaml.YAMLError as exc:
                raise ValueError(f"Error parsing YAML spec: {exc}")
