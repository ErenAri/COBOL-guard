from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_REGISTRY_DIR = REPO_ROOT / "schema-registry"
GOVERNANCE_DIR = REPO_ROOT / "governance"
KEYS_DIR = GOVERNANCE_DIR / "keys"
RUNS_DIR = REPO_ROOT / "runs"
BASELINES_DIR = REPO_ROOT / "baselines"
