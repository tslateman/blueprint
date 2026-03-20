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

                # Validate timer triggers
                for trigger in spec["triggers"]:
                    ttype = trigger.get("type", "file")
                    if ttype not in ("file", "timer"):
                        raise ValueError(f"Unknown trigger type: '{ttype}'")

                    if ttype == "timer":
                        has_interval = "interval" in trigger
                        has_cron = "cron" in trigger

                        if has_cron:
                            raise NotImplementedError(
                                "Cron expressions are not yet supported"
                            )
                        if not has_interval and not has_cron:
                            raise ValueError(
                                "Timer trigger requires 'interval' or 'cron'"
                            )
                        if has_interval and has_cron:
                            raise ValueError(
                                "Timer trigger cannot have both 'interval' and 'cron'"
                            )
                        if has_interval and (
                            not isinstance(trigger["interval"], (int, float))
                            or trigger["interval"] <= 0
                        ):
                            raise ValueError(
                                "Timer 'interval' must be a positive number (seconds)"
                            )

                        action = trigger.get("action", "enforcer")
                        if action == "enforcer" and "input" not in trigger:
                            raise ValueError(
                                "Timer trigger with action 'enforcer' requires 'input'"
                            )
                        if action == "fleet" and "payload_path" not in trigger:
                            raise ValueError(
                                "Timer trigger with action 'fleet' requires 'payload_path'"
                            )

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
