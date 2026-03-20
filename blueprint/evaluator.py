import json
import time
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, Field
from blueprint.enforcer import SchemaEnforcer
from blueprint.parser import SpecParser
from blueprint.compiler import BlueprintCompiler
from unittest.mock import patch

class EvalResult(BaseModel):
    passed: bool
    reason: str

class LLMJudge:
    """Uses a specialized LLM call to evaluate semantic assertions."""
    
    def __init__(self, enforcer: SchemaEnforcer):
        self.enforcer = enforcer
        
    def evaluate(self, output: Dict[str, Any], assertion_prompt: str) -> EvalResult:
        class GradeOutput(BaseModel):
            passed: bool = Field(..., description="Whether the assertion passed.")
            reason: str = Field(..., description="A brief explanation for the grade.")
            
        system_prompt = (
            "You are a rigorous quality assurance grader. Your task is to evaluate the output of an AI agent "
            "against a specific assertion. Be objective and fair."
        )
        
        user_prompt = (
            f"### Agent Output:\n{json.dumps(output, indent=2)}\n\n"
            f"### Assertion to Verify:\n{assertion_prompt}\n\n"
            "Does the output satisfy the assertion?"
        )
        
        return self.enforcer.generate(system_prompt, user_prompt, GradeOutput)

class EvaluatorHarness:
    """Executes blueprints and grades them against golden cases."""
    
    def __init__(self, enforcer: Optional[SchemaEnforcer] = None, use_cli: bool = False):
        self.enforcer = enforcer or SchemaEnforcer(use_cli=use_cli)
        self.judge = LLMJudge(self.enforcer)
        
    def run_case(self, case: Dict[str, Any]) -> List[EvalResult]:
        # Small delay to respect rate limits during batch evals (CLI mode only)
        import os
        if os.getenv("USE_GEMINI_CLI", "").lower() == "true":
            time.sleep(1)
        
        spec_path = case['spec_path']
        input_text = case['input']
        spec = SpecParser.parse_yaml(spec_path)
        
        # Setup mocks for Lore if provided
        lore_mocks = case.get('lore_mocks', {})

        def lore_resolver(query):
            return lore_mocks.get(query, f"No mock data for: {query}")

        # 1. Compile and Execute
        system_prompt = BlueprintCompiler.compile_prompt(spec, lore_resolver=lore_resolver)
        ResponseModel = BlueprintCompiler.compile_schema(spec)

        result_model = self.enforcer.generate(system_prompt, input_text, ResponseModel)
        output_dict = result_model.model_dump()

        # 2. Grade Assertions
        results = []
        for assertion in case['assertions']:
            res = self._grade_assertion(output_dict, assertion)
            results.append(res)

        return results

    def _grade_assertion(self, output: Dict[str, Any], assertion: Dict[str, Any]) -> EvalResult:
        a_type = assertion['type']
        field = assertion.get('field')
        
        if a_type in ("field_matches", "field_equals"):
            val = output.get(field)
            expected = assertion['value']
            if val == expected:
                return EvalResult(passed=True, reason=f"Field '{field}' matches '{expected}'.")
            return EvalResult(passed=False, reason=f"Field '{field}' was '{val}', expected '{expected}'.")

        elif a_type == "field_contains":
            val = output.get(field, [])
            expected = assertion['value']
            if expected in val:
                return EvalResult(passed=True, reason=f"Field '{field}' contains '{expected}'.")
            return EvalResult(passed=False, reason=f"Field '{field}' did not contain '{expected}'. Current: {val}")

        elif a_type == "field_range":
            val = output.get(field)
            min_val = assertion.get("min")
            max_val = assertion.get("max")
            if val is None:
                return EvalResult(passed=False, reason=f"Field '{field}' is missing or None")
            passed = True
            if min_val is not None and val < min_val:
                passed = False
            if max_val is not None and val > max_val:
                passed = False
            range_str = f"[{min_val if min_val is not None else '-∞'}, {max_val if max_val is not None else '+∞'}]"
            return EvalResult(passed=passed, reason=f"{field}={val} {'within' if passed else 'outside'} {range_str}")

        elif a_type == "semantic":
            return self.judge.evaluate(output, assertion['prompt'])

        return EvalResult(passed=False, reason=f"Unknown assertion type: {a_type}")
