from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from rubric_gen.runtime.agents.resource_limits import limited_agent_command


def _writer_command(path: Path, size: int) -> list[str]:
    return [
        sys.executable,
        "-c",
        "from pathlib import Path; import sys; "
        "Path(sys.argv[1]).write_bytes(b'x' * int(sys.argv[2]))",
        str(path),
        str(size),
    ]


def test_agent_file_limit_allows_bounded_output(tmp_path: Path) -> None:
    output = tmp_path / "bounded.bin"

    completed = subprocess.run(
        limited_agent_command(_writer_command(output, 4096), max_file_bytes=8192),
        check=False,
    )

    assert completed.returncode == 0
    assert output.stat().st_size == 4096


def test_agent_file_limit_blocks_oversized_output(tmp_path: Path) -> None:
    output = tmp_path / "oversized.bin"

    completed = subprocess.run(
        limited_agent_command(_writer_command(output, 8192), max_file_bytes=4096),
        check=False,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert output.stat().st_size <= 4096
