"""
Blueprint Registry
Manages the mapping between project model names and their corresponding 
Blueprint specification files.
"""

import os
from pathlib import Path
from typing import Dict, Optional

class BlueprintRegistry:
    """Registry for looking up Blueprints by model/domain."""
    
    def __init__(self, blueprints_dir: str = "blueprints"):
        self.blueprints_dir = Path(blueprints_dir)
        self._registry: Dict[str, str] = {
            "plan.FeatureEntitlement": "factory_generator/plan_entitlements.yaml",
            "tips.Configuration": "factory_generator/tipping_config.yaml",
            "payments.GatewayProfile": "factory_generator/payments_gateway.yaml",
        }

    def get_spec_path(self, model_name: str) -> Optional[str]:
        """Returns the absolute path to a blueprint spec for a given model."""
        rel_path = self._registry.get(model_name)
        if not rel_path:
            return None
        return str(self.blueprints_dir / rel_path)

    def register(self, model_name: str, spec_rel_path: str):
        """Register a new model-to-blueprint mapping."""
        self._registry[model_name] = spec_rel_path

    def list_models(self) -> Dict[str, str]:
        """Returns all registered model mappings."""
        return self._registry.copy()
