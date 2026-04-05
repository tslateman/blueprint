import os
import re
import json
import logging
import subprocess
import instructor
import diskcache
import hashlib
import anthropic
from openai import OpenAI
from google import genai
from typing import Any, Dict, Type, Optional, TYPE_CHECKING
from pydantic import BaseModel
from dotenv import load_dotenv

from blueprint.compiler import _cmux_progress, _cmux_clear_progress

if TYPE_CHECKING:
    from blueprint.tracer import TracingCollector

logger = logging.getLogger(__name__)


class SchemaEnforcer:
    """Uses Instructor or Gemini CLI to enforce structured output generation."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: Optional[str] = None,
        use_cli: bool = False,
        cache_dir: str = ".eval_cache",
    ):
        self.cache = diskcache.Cache(cache_dir)

        # 1. Check for explicit keys or provider
        has_keys = any(
            os.environ.get(k)
            for k in ["ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"]
        )

        # 2. Decide whether to use CLI
        # If use_cli is forced OR (no keys found AND no explicit provider/api_key)
        self.use_cli = use_cli or (not has_keys and not provider and not api_key)

        if self.use_cli:
            # Check if gemini is in PATH
            try:
                subprocess.run(["gemini", "--version"], capture_output=True, check=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                if (
                    use_cli
                ):  # Only raise if they explicitly ASKED for CLI and it's missing
                    raise RuntimeError(
                        "Gemini CLI ('gemini') not found in PATH. Cannot use CLI mode."
                    )
                # Otherwise, let it fall through to the key check which will fail with a helpful message
                self.use_cli = False

        if self.use_cli:
            return

        if not provider:
            if os.environ.get("ANTHROPIC_API_KEY"):
                provider = "anthropic"
            elif os.environ.get("GEMINI_API_KEY"):
                provider = "gemini"
            elif os.environ.get("OPENAI_API_KEY"):
                provider = "openai"
            else:
                raise ValueError(
                    "No API key (ANTHROPIC, GEMINI, or OPENAI) found in environment, and Gemini CLI fallback failed."
                )

        self.provider = provider
        if provider == "anthropic":
            self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            self.client = instructor.from_anthropic(
                anthropic.Anthropic(api_key=self.api_key)
            )
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

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[BaseModel],
        model: Optional[str] = None,
        tracer: "Optional[TracingCollector]" = None,
    ) -> BaseModel:
        """Generates a structured response strictly enforcing the response_model schema (cached)."""
        model_name = model or getattr(self, "default_model", "gemini-cli")

        # Create a cache key from prompt and schema
        schema_json = json.dumps(response_model.model_json_schema(), sort_keys=True)
        key_data = f"{system_prompt}|{user_prompt}|{model_name}|{response_model.__name__}|{schema_json}"
        cache_key = hashlib.md5(key_data.encode()).hexdigest()
        cache_key_hash = cache_key

        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.debug("Cache hit for key %s", cache_key_hash)
            return response_model.model_validate_json(cached_result)

        # Build list of available API providers in priority order
        providers = []
        if os.environ.get("ANTHROPIC_API_KEY"):
            providers.append(
                (
                    "anthropic",
                    model or "claude-3-5-sonnet-latest",
                    lambda: instructor.from_anthropic(
                        anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
                    ),
                )
            )
        if os.environ.get("GEMINI_API_KEY"):
            providers.append(
                (
                    "gemini",
                    model or "gemini-2.5-flash",
                    lambda: instructor.from_genai(
                        genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
                    ),
                )
            )
        if os.environ.get("OPENAI_API_KEY"):
            providers.append(
                (
                    "openai",
                    model or "gpt-4o-mini",
                    lambda: instructor.from_openai(
                        OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
                    ),
                )
            )

        # If a specific provider was pre-selected on the instance, use only that one
        if hasattr(self, "provider") and not self.use_cli:
            providers = [p for p in providers if p[0] == self.provider]
            if not providers:
                # Fall back to the already-constructed client on the instance
                providers = [(self.provider, model_name, lambda: self.client)]

        tried = []
        result = None
        for provider_name, provider_model, client_factory in providers:
            logger.info("Using provider: %s (model: %s)", provider_name, provider_model)
            logger.debug("Cache miss — calling %s API", provider_name)
            try:
                client = client_factory()
                _cmux_progress(0.5, f"generating ({provider_name})...")
                result = client.chat.completions.create(
                    model=provider_model,
                    response_model=response_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                _cmux_clear_progress()
                if tracer:
                    try:
                        tracer.emit(
                            "llm_call",
                            {
                                "provider": provider_name,
                                "model": provider_model,
                                "success": True,
                            },
                        )
                    except Exception:
                        pass
                break
            except Exception as e:
                logger.warning("Provider %s failed: %s — trying next", provider_name, e)
                tried.append(provider_name)
                if tracer:
                    try:
                        tracer.emit(
                            "llm_call",
                            {
                                "provider": provider_name,
                                "model": provider_model,
                                "success": False,
                                "error": str(e),
                            },
                        )
                    except Exception:
                        pass

        if result is None:
            # All API providers failed — try CLI as final fallback
            if self.use_cli or os.environ.get("USE_GEMINI_CLI"):
                logger.warning("Falling back to Gemini CLI mode")
                if tracer:
                    try:
                        tracer.emit(
                            "llm_fallback", {"target": "gemini_cli", "tried": tried}
                        )
                    except Exception:
                        pass
                result = self._generate_via_cli(
                    system_prompt, user_prompt, response_model
                )
            else:
                raise RuntimeError(
                    f"All providers failed: {', '.join(tried)}. No result could be generated."
                )

        # Store successful result as JSON
        self.cache.set(cache_key, result.model_dump_json())
        return result

    def _generate_via_cli(
        self, system_prompt: str, user_prompt: str, response_model: Type[BaseModel]
    ) -> BaseModel:
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
            response_text = re.sub(r"^```[a-z]*\s*", "", response_text.strip())
            response_text = re.sub(r"\s*```$", "", response_text)

            return response_model.model_validate_json(response_text)
        except (json.JSONDecodeError, ValueError) as e:
            raise RuntimeError(
                f"Failed to parse CLI output into {response_model.__name__}: {e}\nRaw Output: {result.stdout}"
            )
