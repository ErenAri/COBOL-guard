from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CheckpointManager:
    state_root: Path

    def _path(self, run_id: str) -> Path:
        return self.state_root / f"{run_id}.checkpoint.json"

    def load(self, run_id: str) -> dict[str, Any]:
        path = self._path(run_id=run_id)
        if not path.exists():
            return {
                "run_id": run_id,
                "chunks": {},
                "engine_state": {},
                "last_committed_chunk_index": -1,
            }
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, run_id: str, state: dict[str, Any]) -> None:
        path = self._path(run_id=run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def ensure(self, run_id: str, target: str, chunk_size: int) -> dict[str, Any]:
        state = self.load(run_id=run_id)
        state.setdefault("target", target)
        state.setdefault("chunk_size", int(chunk_size))
        state.setdefault("chunks", {})
        state.setdefault("engine_state", {})
        state.setdefault("last_committed_chunk_index", -1)
        self.save(run_id=run_id, state=state)
        return state

    def get_engine_state(self, run_id: str) -> dict[str, Any]:
        state = self.load(run_id=run_id)
        return dict(state.get("engine_state", {}))

    def set_engine_state(self, run_id: str, engine_state: dict[str, Any]) -> None:
        state = self.load(run_id=run_id)
        state["engine_state"] = dict(engine_state)
        self.save(run_id=run_id, state=state)

    def mark_chunk_committed(
        self,
        run_id: str,
        chunk_id: str,
        last_unit_of_work: str,
        input_fingerprint: str,
        chunk_index: int,
        chunk_manifest: dict[str, Any],
        engine_state: dict[str, Any],
    ) -> None:
        state = self.load(run_id=run_id)
        state["chunks"][chunk_id] = {
            "committed": True,
            "chunk_index": int(chunk_index),
            "last_unit_of_work": last_unit_of_work,
            "input_fingerprint": input_fingerprint,
            "chunk_manifest": chunk_manifest,
        }
        state["last_committed_chunk_index"] = max(int(state.get("last_committed_chunk_index", -1)), int(chunk_index))
        state["engine_state"] = dict(engine_state)
        self.save(run_id=run_id, state=state)

    def is_chunk_committed(self, run_id: str, chunk_id: str) -> bool:
        state = self.load(run_id=run_id)
        return bool(state.get("chunks", {}).get(chunk_id, {}).get("committed", False))

    def committed_chunk_ids(self, run_id: str) -> list[str]:
        state = self.load(run_id=run_id)
        chunks = state.get("chunks", {})
        committed = [chunk_id for chunk_id, payload in chunks.items() if payload.get("committed")]
        return sorted(committed)

    def chunk_payload(self, run_id: str, chunk_id: str) -> dict[str, Any]:
        state = self.load(run_id=run_id)
        return dict(state.get("chunks", {}).get(chunk_id, {}))
