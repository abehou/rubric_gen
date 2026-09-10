"""Exercise the real wrapper cleanup under the installed SDK's shutdown budget."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def test_wrapper_restores_tmp_before_sdk_shutdown_deadline(tmp_path: Path):
    home = tmp_path / "codex-home"
    home.mkdir()
    wrapper = tmp_path / "wrapper.py"
    wrapper.write_text('''
import signal
import subprocess
import sys
import time
from pathlib import Path
from rubric_gen.runtime.agents.codex_app_server import _local_cli_temporary, _terminate

root = Path(sys.argv[1])
with _local_cli_temporary(root / "codex-home", root / "runtime"):
    child = subprocess.Popen(
        [sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('ready',flush=True); time.sleep(30)"],
        stdout=subprocess.PIPE, text=True,
    )
    assert child.stdout.readline().strip() == "ready"
    def stop(*args):
        _terminate(child)
        raise SystemExit(143)
    signal.signal(signal.SIGTERM, stop)
    (root / "ready").write_text("ready")
    try:
        while True:
            time.sleep(.05)
    finally:
        _terminate(child)
''')
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    process = subprocess.Popen(
        [sys.executable, str(wrapper), str(tmp_path)],
        env=environment,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 20
        while not (tmp_path / "ready").exists() and time.monotonic() < deadline:
            assert process.poll() is None
            time.sleep(.02)
        assert (tmp_path / "ready").is_file()
        process.terminate()
        try:
            process.wait(timeout=2)  # openai_codex.client.CodexClient.close
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        assert process.returncode == 143
        assert not os.path.lexists(home / "tmp")
        assert not list(home.glob(".tmp-preserved-*"))
    finally:
        # Every child in this group belongs to this synthetic test.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=2)
