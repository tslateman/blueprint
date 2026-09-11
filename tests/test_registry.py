import os
from pathlib import Path

from blueprint.registry import BlueprintRegistry


def test_all_registered_specs_exist():
    registry = BlueprintRegistry(blueprints_dir=str(Path(__file__).parent.parent / "blueprints"))
    for model_name, spec_path in registry.list_models().items():
        full_path = registry.get_spec_path(model_name)
        assert os.path.exists(full_path), f"{model_name} -> {spec_path} does not exist"
