import os
import json
import os
import json
import subprocess
import instructor
import diskcache
import hashlib
import anthropic
from openai import OpenAI
from google import genai
from typing import Any, Dict, Type, Optional
from pydantic import BaseModel
from dotenv import load_dotenv
...
class SchemaEnforcer:
    """Uses Instructor or Gemini CLI to enforce structured output generation."""

    def __init__(self, api_key: Optional[str] = None, provider: Optional[str] = None, use_cli: bool = False, cache_dir: str = ".eval_cache"):
        self.use_cli = use_cli
        self.cache = diskcache.Cache(cache_dir)

        if use_cli:
            # Check if gemini is in PATH
            try:
                subprocess.run(["gemini", "--version"], capture_output=True, check=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                raise RuntimeError("Gemini CLI ('gemini') not found in PATH. Cannot use CLI mode.")
            return

        if not provider:
            if os.environ.get("ANTHROPIC_API_KEY"):
                provider = "anthropic"
            elif os.environ.get("GEMINI_API_KEY"):
                provider = "gemini"
            elif os.environ.get("OPENAI_API_KEY"):
                provider = "openai"
            else:
                raise ValueError("No API key (ANTHROPIC, GEMINI, or OPENAI) found in environment.")

        self.provider = provider
        if provider == "anthropic":
            self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            self.client = instructor.from_anthropic(anthropic.Anthropic(api_key=self.api_key))
            self.default_model = "claude-3-5-sonnet-latest"
        elif provider == "openai":
            self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
            self.client = instructor.from_openai(OpenAI(api_key=self.api_key))
            self.default_model = "gpt-4o-mini"
        elif provider == "gemini":
            self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
            self.client = instructor.from_genai(genai.Client(api_key=self.api_key))
            self.default_model = "gemini-2.5-flash"
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        
    def generate(self, system_prompt: str, user_prompt: str, response_model: Type[BaseModel], model: Optional[str] = None) -> BaseModel:
        """Generates a structured response strictly enforcing the response_model schema (cached)."""
        model_name = model or getattr(self, "default_model", "gemini-cli")
        
        # Create a cache key from prompt and schema
        key_data = f"{system_prompt}|{user_prompt}|{model_name}|{response_model.__name__}"
        cache_key = hashlib.md5(key_data.encode()).hexdigest()
        
        cached_result = self.cache.get(cache_key)
        if cached_result:
            return response_model.model_validate_json(cached_result)

        if self.use_cli:
            result = self._generate_via_cli(system_prompt, user_prompt, response_model)
        else:
            result = self.client.chat.completions.create(
                model=model_name,
                response_model=response_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            
        # Store successful result as JSON
        self.cache.set(cache_key, result.model_dump_json())
        return result

    def _generate_via_cli(self, system_prompt: str, user_prompt: str, response_model: Type[BaseModel]) -> BaseModel:
        """Calls the Gemini CLI in headless mode to generate structured output."""
        schema_json = json.dumps(response_model.model_json_schema(), indent=2)
        
        # We craft a prompt that instructs the CLI to return JSON matching the schema
        full_prompt = (
            f"{system_prompt}\n\n"
            f"USER INPUT: {user_prompt}\n\n"
            f"CRITICAL: You must return ONLY a JSON object that strictly adheres to this JSON Schema:\n{schema_json}"
        )
        
        cmd = ["gemini", "--output-format", "json", full_prompt]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Gemini CLI error: {result.stderr}")
            
        try:
            cli_data = json.loads(result.stdout)
            # The CLI returns a wrapper JSON. We need the model's actual response text.
            response_text = cli_data.get("response", "")
            
            # Clean up potential markdown formatting if the model included it
            if response_text.startswith("```json"):
                response_text = response_text.replace("```json", "", 1).replace("```", "", 1).strip()
            elif response_text.startswith("```"):
                response_text = response_text.replace("```", "", 1).replace("```", "", 1).strip()
                
            return response_model.model_validate_json(response_text)
        except (json.JSONDecodeError, ValueError) as e:
            raise RuntimeError(f"Failed to parse CLI output into {response_model.__name__}: {e}\nRaw Output: {result.stdout}")
