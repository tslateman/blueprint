import yaml
from pathlib import Path
from typing import Any, Dict


class SpecParser:
    """Parses Declarative Blueprint specifications from YAML/Markdown."""

    @staticmethod
    def parse_yaml(file_path: str | Path) -> Dict[str, Any]:
        """Reads a YAML spec file, returns a dictionary, and performs basic validation."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Spec file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            try:
                spec = yaml.safe_load(f)

                # Basic Validation
                if not spec or not isinstance(spec, dict):
                    raise ValueError("Spec must be a non-empty YAML dictionary.")
                # Ensure triggers is a list if present
                if "triggers" in spec and not isinstance(spec["triggers"], list):
                    spec["triggers"] = [spec["triggers"]]
                elif "triggers" not in spec:
                    spec["triggers"] = []

                # Validate trigger actions
                actions = {t.get("action", "enforcer") for t in spec["triggers"]}
                invalid = actions - {"enforcer", "fleet"}
                if invalid:
                    raise ValueError(f"Unknown trigger action(s): {invalid}")

                # Only require intent/output_schema for enforcer or triggerless specs
                needs_llm = "enforcer" in actions or not spec["triggers"]
                if needs_llm:
                    if "intent" not in spec:
                        raise ValueError("Blueprint must define an 'intent'.")
                    if "output_schema" not in spec:
                        raise ValueError("Blueprint must define an 'output_schema'.")

                return spec
            except yaml.YAMLError as exc:
                raise ValueError(f"Error parsing YAML spec: {exc}")
