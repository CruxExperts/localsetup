"""Documentation alignment package."""

from .audit import audit, build_plan
from .assets import collect_asset_manifest
from .cli import main
from .inventory import collect_inventory, collect_truth_map
from .writers import generate_alignment_artifacts

__all__ = [
    "audit",
    "build_plan",
    "collect_asset_manifest",
    "collect_inventory",
    "collect_truth_map",
    "generate_alignment_artifacts",
    "main",
]
