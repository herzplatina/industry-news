import json
from pathlib import Path

CHECKPOINT_PATH = Path(__file__).resolve().parent.parent / "data" / "checkpoint.json"


def load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text())
    return {}


def save_checkpoint(checkpoint: dict) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(checkpoint, indent=2))
