"""Run one supervised `aisim predict` and capture AISim's native block-level replay artifacts.

The replay runs in AISim's normal supervised child process. `_hook/sitecustomize.py`
(enabled through PYTHONPATH + KV_TRACE_OUT) swaps in the runtime's own
`run_replay_with_artifacts_json` there. No upstream AISim file is modified.

Usage (run with the AISim venv's Python):
    python capture.py --trace-out OUT/trace.json -- predict --stack engine \
        --config CONFIG.yaml --capture-per-request --output-dir OUT/aisim
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "_hook"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trace-out", required=True, type=Path, help="where to write spec + artifacts JSON")
    parser.add_argument("aisim_args", nargs=argparse.REMAINDER, help="arguments for `aisim` after `--`")
    args = parser.parse_args()
    aisim_args = args.aisim_args[1:] if args.aisim_args[:1] == ["--"] else args.aisim_args
    trace_out = args.trace_out.resolve()
    trace_out.parent.mkdir(parents=True, exist_ok=True)
    trace_out.unlink(missing_ok=True)
    env = dict(os.environ, KV_TRACE_OUT=str(trace_out),
               PYTHONPATH=os.pathsep.join(filter(None, [str(HOOK), os.environ.get("PYTHONPATH")])))
    aisim = Path(sys.executable).parent / "aisim"
    status = subprocess.run([str(aisim), *aisim_args], env=env).returncode
    if status != 0:
        return status
    if not trace_out.exists():
        sys.stderr.write(f"aisim finished but no replay was captured at {trace_out}\n")
        return 1
    artifacts = json.loads(trace_out.read_text())["artifacts"]
    print(f"trace: {trace_out} (kv_events={len(artifacts['kv_events'])}, "
          f"host_offload_events={len(artifacts['host_offload_events'])}, requests={len(artifacts['requests'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
