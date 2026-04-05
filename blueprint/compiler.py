import os
import subprocess
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING
from pydantic import BaseModel, create_model, Field

if TYPE_CHECKING:
    from blueprint.tracer import TracingCollector

_CMUX = "/Applications/cmux.app/Contents/Resources/bin/cmux"


def _cmux_progress(value: float, label: str) -> None:
    if not os.environ.get("CMUX_WORKSPACE_ID") or not os.path.isfile(_CMUX):
        return
    subprocess.Popen(
        [_CMUX, "set-progress", f"{value:.2f}", "--label", label],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _cmux_clear_progress() -> None:
    if not os.environ.get("CMUX_WORKSPACE_ID") or not os.path.isfile(_CMUX):
        return
    subprocess.Popen(
        [_CMUX, "clear-progress"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class BlueprintCompiler:
    """Compiles a parsed spec into a system prompt and a Pydantic model for structured generation."""

    @staticmethod
    def compile_prompt(
        spec: Dict[str, Any],
        lore_resolver=None,
        tracer: "Optional[TracingCollector]" = None,
    ) -> str:
        """Constructs the system prompt based on intents, constraints, and instructions."""
        intent = spec.get("intent", "You are a helpful AI assistant.")
        constraints = spec.get("constraints", [])
        instructions = spec.get("instructions", [])

        prompt_parts = []
        prompt_parts.append(f"# Intent\n{intent}\n")

        if constraints:
            prompt_parts.append(
                "# Constraints\nYou must strictly adhere to the following constraints:"
            )
            for c in constraints:
                prompt_parts.append(f"- {c}")
            prompt_parts.append("")

        if instructions:
            prompt_parts.append("# Instructions")
            for i in instructions:
                prompt_parts.append(f"- {i}")
            prompt_parts.append("")

        # Tools Documentation
        tools_allowed = spec.get("tools_allowed", [])
        if tools_allowed:
            prompt_parts.append(
                "# Tools Available\nYou have access to the following tools via your output schema fields:"
            )
            if "lore_record_decision" in tools_allowed:
                prompt_parts.append(
                    "- lore_record_decision: Record a technical decision and its rationale into long-term memory."
                )
            prompt_parts.append("")

        # Optional Lore Context Hydration
        # We trigger this if explicitly defined OR if lore_search is allowed
        lore_queries = spec.get("lore_context", [])
        if ("lore_search" in tools_allowed) or lore_queries:
            if lore_resolver is None:
                from vault.tool_router import ToolRouter

                router = ToolRouter()
                lore_resolver = router.lore_search
            prompt_parts.append(
                "# Lore Context\nThe following background context was retrieved from the system's long-term memory:\n"
            )

            # If no queries were provided but lore_search is allowed, we might want to default to some generic ones
            # or skip if empty. Let's assume lore_context should still be provided if they want context.
            for i, query in enumerate(lore_queries):
                _cmux_progress((i + 1) / len(lore_queries), f"lore: {query}")
                result = lore_resolver(query)
                if tracer:
                    try:
                        tracer.emit(
                            "lore_recall",
                            {
                                "query": query,
                                "result_length": len(result) if result else 0,
                            },
                        )
                    except Exception:
                        pass
                if result and (
                    result.lower().startswith("error")
                    or "command not found" in result.lower()
                    or "not found" in result.lower()
                    and len(result) < 100
                ):
                    prompt_parts.append(
                        f"### Query: {query}\n_Lore context unavailable for this query._"
                    )
                else:
                    prompt_parts.append(f"### Query: {query}\n```text\n{result}\n```")
            _cmux_clear_progress()

        if tracer:
            try:
                tracer.emit(
                    "prompt_compile",
                    {"queries": len(lore_queries), "intent": intent[:80]},
                )
            except Exception:
                pass

        return "\n".join(prompt_parts)

    @staticmethod
    def compile_schema(
        spec: Dict[str, Any],
        model_name: str = "DynamicOutput",
        tracer: "Optional[TracingCollector]" = None,
    ) -> Type[BaseModel]:
        """Creates a dynamic Pydantic model from the 'output_schema' section of the spec."""
        schema_def = spec.get("output_schema")
        if not schema_def:
            raise ValueError("No 'output_schema' defined in the spec.")

        fields = {}
        # Basic mapping of type string to Python type.
        # In a real system, you'd handle nested objects, arrays, etc.
        type_mapping = {
            "string": str,
            "integer": int,
            "float": float,
            "boolean": bool,
            "array": List[str],  # Defaulting arrays to list of strings for now
        }

        for field_name, field_info in schema_def.items():
            field_type_str = field_info.get("type", "string")
            description = field_info.get("description", "")
            is_optional = field_info.get("optional", False)

            if field_type_str.lower() == "array":
                items_spec = field_info.get("items", {})
                item_type_str = (
                    items_spec.get("type", "string") if items_spec else "string"
                )
                scalar_map = {k: v for k, v in type_mapping.items() if k != "array"}
                item_type = scalar_map.get(item_type_str.lower(), str)
                python_type = List[item_type]
            else:
                python_type = type_mapping.get(field_type_str.lower(), str)

            if is_optional:
                fields[field_name] = (
                    Optional[python_type],
                    Field(None, description=description),
                )
            else:
                fields[field_name] = (python_type, Field(..., description=description))

        if tracer:
            try:
                tracer.emit(
                    "schema_compile",
                    {"model_name": model_name, "field_count": len(fields)},
                )
            except Exception:
                pass

        return create_model(model_name, **fields)
