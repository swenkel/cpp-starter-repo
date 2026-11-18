"""Behavioral application smoke tests, also used in coverage/sanitizer builds."""
import os
import select
import subprocess
import time
import urllib.request
from . import common as c

def application(cfg, directory, env):
    if cfg["profile"] in {"library", "header-only"}:
        return
    binary = directory / "app"
    if cfg["profile"] == "qt":
        binary = directory / "gui_smoke"
    if cfg["profile"] != "http":
        output = c.run([binary], env=env, capture=True)
        expected = {"cli": "-1", "numerical": "25"}.get(cfg["profile"])
        if expected and output.strip() != expected:
            raise c.Failure(f"application returned unexpected output: {output!r}")
        return
    env = env.copy()
    env.pop("HOST", None)
    process = subprocess.Popen([str(binary)], cwd=c.ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        readable, _, _ = select.select([process.stdout], [], [], 15)
        if not readable:
            raise c.Failure("HTTP server did not report its port")
        line = process.stdout.readline().strip()
        try:
            port = int(line)
        except ValueError as error:
            raise c.Failure("HTTP server exited without a port") from error
        error = None
        for attempt in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                    if response.status != 200 or response.read() != b"ok":
                        raise c.Failure("health endpoint contract failed")
                break
            except OSError as exc:
                error = exc
                time.sleep(0.1)
        else:
            raise c.Failure(f"HTTP server unavailable: {error}")
        process.terminate()
        out, err = process.communicate(timeout=15)
        if process.returncode:
            raise c.Failure(f"HTTP shutdown failed ({process.returncode}): {err}")
        # A reserved non-local address exercises bind failure without DNS access.
        failure = subprocess.run([str(binary)], cwd=c.ROOT, env=env | {"HOST": "192.0.2.1"}, capture_output=True, text=True, timeout=15)
        if failure.returncode != 1:
            raise c.Failure("HTTP server did not reject an unavailable bind address")
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
