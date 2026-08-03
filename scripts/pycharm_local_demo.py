"""PyCharm entry point for the Windows local synthetic demonstration."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop"))
    arguments = parser.parse_args()

    repository_root = Path(__file__).parents[1]
    script_name = "start_local_demo.ps1" if arguments.action == "start" else "stop_local_demo.ps1"
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(repository_root / "scripts" / script_name),
    ]
    if arguments.action == "start":
        command.extend(("-SkipInstall", "-OpenBrowser"))

    print(f"PyCharm local demo: {arguments.action}...", flush=True)
    result = subprocess.run(command, cwd=repository_root, check=False)
    if result.returncode == 0 and arguments.action == "start":
        process_file = repository_root / "scripts" / ".local-demo-processes.json"
        if process_file.exists():
            process_data = json.loads(process_file.read_text(encoding="utf-8-sig"))
            print(
                f"Ready. Consumer page: http://127.0.0.1:{process_data['frontend_port']}",
                flush=True,
            )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
