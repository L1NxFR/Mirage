"""Loaded only when capture.py puts this folder on PYTHONPATH with KV_TRACE_OUT set.

AISim runs the replay in a supervised child process (`python -m
aisim.resource_worker`), so the patch must be installed in every interpreter
the CLI starts. It swaps `run_replay_json` for the runtime's own
`run_replay_with_artifacts_json` (same replay loop, plus native KV/G2
observations), writes the artifacts to KV_TRACE_OUT, and returns the plain
report so the CLI behaves exactly as before.
"""

import json
import os

_OUT = os.environ.get("KV_TRACE_OUT")
if _OUT:
    import aisim._runtime as _runtime

    _original = _runtime.run_replay_with_artifacts_json

    def run_replay_json(execution_spec_json: str) -> str:
        if os.path.exists(_OUT):
            raise RuntimeError(f"kv-trace captures exactly one replay; {_OUT} already exists")
        output = json.loads(_original(execution_spec_json))
        with open(_OUT, "w") as handle:
            json.dump({"execution_spec": json.loads(execution_spec_json), "artifacts": output["artifacts"]}, handle, indent=1)
        return json.dumps(output["report"], allow_nan=False, separators=(",", ":"))

    _runtime.run_replay_json = run_replay_json
