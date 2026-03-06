from typing import Any, Dict, List, Type
from pydantic import BaseModel, create_model, Field

class BlueprintCompiler:
    """Compiles a parsed spec into a system prompt and a Pydantic model for structured generation."""
    
    @staticmethod
    def compile_prompt(spec: Dict[str, Any]) -> str:
        """Constructs the system prompt based on intents, constraints, and instructions."""
        intent = spec.get('intent', 'You are a helpful AI assistant.')
        constraints = spec.get('constraints', [])
        instructions = spec.get('instructions', [])
        
        prompt_parts = []
        prompt_parts.append(f"# Intent\n{intent}\n")
        
        if constraints:
            prompt_parts.append("# Constraints\nYou must strictly adhere to the following constraints:")
            for c in constraints:
                prompt_parts.append(f"- {c}")
            prompt_parts.append("")
            
        if instructions:
            prompt_parts.append("# Instructions")
            for i in instructions:
                prompt_parts.append(f"- {i}")
            prompt_parts.append("")
            
        # Tools Documentation
        tools_allowed = spec.get('tools_allowed', [])
        if tools_allowed:
            prompt_parts.append("# Tools Available\nYou have access to the following tools via your output schema fields:")
            if "lore_record_decision" in tools_allowed:
                prompt_parts.append("- lore_record_decision: Record a technical decision and its rationale into long-term memory.")
            prompt_parts.append("")
            
        # Optional Lore Context Hydration
        # We trigger this if explicitly defined OR if lore_search is allowed
        lore_queries = spec.get('lore_context', [])
        if ("lore_search" in tools_allowed) or lore_queries:
            # Import router here to avoid circular dep if needed, or assume it's available.
            # Best practice is to decouple, but for prototype we just assume ToolRouter is used.
            from vault.tool_router import ToolRouter
            router = ToolRouter()
            prompt_parts.append("# Lore Context\nThe following background context was retrieved from the system's long-term memory:\n")
            
            # If no queries were provided but lore_search is allowed, we might want to default to some generic ones
            # or skip if empty. Let's assume lore_context should still be provided if they want context.
            for query in lore_queries:
                prompt_parts.append(f"### Query: {query}")
                result = router.lore_search(query)
                prompt_parts.append(f"```text\n{result}\n```\n")
                
        return "\n".join(prompt_parts)

    @staticmethod
    def compile_schema(spec: Dict[str, Any], model_name: str = "DynamicOutput") -> Type[BaseModel]:
        """Creates a dynamic Pydantic model from the 'output_schema' section of the spec."""
        schema_def = spec.get('output_schema')
        if not schema_def:
            raise ValueError("No 'output_schema' defined in the spec.")
            
        fields = {}
        # Basic mapping of type string to Python type. 
        # In a real system, you'd handle nested objects, arrays, etc.
        type_mapping = {
            'string': str,
            'integer': int,
            'float': float,
            'boolean': bool,
            'array': List[str], # Defaulting arrays to list of strings for now
        }
        
        for field_name, field_info in schema_def.items():
            field_type_str = field_info.get('type', 'string')
            description = field_info.get('description', '')
            python_type = type_mapping.get(field_type_str.lower(), str)
            
            # For simplicity, assuming all fields are required unless we add logic here.
            fields[field_name] = (python_type, Field(..., description=description))
            
        return create_model(model_name, **fields)
