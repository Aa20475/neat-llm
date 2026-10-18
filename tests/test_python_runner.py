import asyncio
from pathlib import Path
import time

import pytest

from company.agent_tools import python_execute
from company.python_runner import POLICY, run_python


def test_python_writes_imports_executes_and_starts_fresh():
    code = """from helper import double
from pathlib import Path
value = double(int(Path('inputs/value.txt').read_text()))
Path('result.txt').write_text(str(value))
print(Path('result.txt').read_text())
"""
    result = asyncio.run(python_execute.ainvoke({
        "code": code, "files": {"inputs/value.txt": "21", "helper.py": "def double(n): return n * 2"},
    }))
    assert result["status"] == "ok" and result["exit_code"] == 0
    assert result["stdout"] == "42\n" and not result["stderr"]
    fresh = asyncio.run(run_python("from pathlib import Path; print(Path('result.txt').exists())"))
    assert fresh["stdout"] == "False\n"


def test_python_displays_final_expression_and_unittest_discovers_main():
    result = asyncio.run(run_python("values = [n for n in range(1,10001) if n*n % 97 == 4]\nlen(values), sum(values)"))
    assert result["status"] == "ok" and result["stdout"] == "(207, 1039066)\n"
    tests = asyncio.run(run_python("""import unittest
class Example(unittest.TestCase):
    def test_deliberate_failure(self):
        self.assertEqual(2 + 2, 5)
unittest.main()
"""))
    assert tests["status"] == "error"
    assert "Ran 1 test" in tests["stderr"] and "FAILED" in tests["stderr"]


def test_python_cannot_read_host_credentials_or_connect_or_fork(tmp_path, monkeypatch):
    sentinel = tmp_path / "private.txt"
    sentinel.write_text("private-controller-data")
    monkeypatch.setenv("CRUSOE_API_KEY", "test-secret-not-for-workers")
    code = f"""import json, os, pathlib, socket
assert not pathlib.Path({str(sentinel)!r}).exists()
assert not pathlib.Path({str(Path.cwd())!r}).exists()
assert 'CRUSOE_API_KEY' not in os.environ
assert b'test-secret-not-for-workers' not in pathlib.Path('/proc/1/environ').read_bytes()
try:
    socket.create_connection(('1.1.1.1', 80), timeout=0.2)
except OSError:
    pass
else:
    raise AssertionError('network accessible')
try:
    child = os.fork()
except OSError:
    pass
else:
    if child == 0: os._exit(0)
    os.waitpid(child, 0)
    raise AssertionError('fork allowed')
for path in ('/usr/tool-write-test', '/dev/tool-write-test', '/outside-work'):
    try:
        pathlib.Path(path).write_text('no')
    except OSError:
        pass
    else:
        raise AssertionError('system writes allowed')
print('isolated')
"""
    result = asyncio.run(run_python(code))
    assert result["status"] == "ok", result
    assert result["stdout"] == "isolated\n"
    assert sentinel.read_text() == "private-controller-data"


def test_python_reports_errors_and_caps_output():
    error = asyncio.run(run_python("assert 2 + 2 == 5, 'bad arithmetic'"))
    assert error["status"] == "error" and error["exit_code"] != 0
    assert "AssertionError: bad arithmetic" in error["stderr"]
    loud = asyncio.run(run_python("import sys; print('x' * 30000); print('y' * 30000, file=sys.stderr)"))
    assert loud["status"] == "ok"
    assert loud["stdout_truncated"] and loud["stderr_truncated"]
    assert len(loud["stdout"]) == len(loud["stderr"]) == POLICY["output_bytes_per_stream"]


def test_python_resource_limits_cannot_be_raised():
    result = asyncio.run(run_python("""import resource
assert resource.getrlimit(resource.RLIMIT_AS) == (268435456, 268435456)
try:
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
except (ValueError, OSError):
    pass
else:
    raise AssertionError('raised hard memory limit')
try:
    with open('large.bin', 'wb') as file:
        file.write(b'x' * 2097152)
except OSError:
    pass
else:
    raise AssertionError('file limit not enforced')
print('bounded')
"""))
    assert result["status"] == "ok", result
    assert result["stdout"] == "bounded\n"


def test_python_timeout_kills_sandbox(monkeypatch):
    monkeypatch.setitem(POLICY, "wall_seconds", 0.3)
    started = time.monotonic()
    result = asyncio.run(run_python("import time; time.sleep(60)"))
    assert result["status"] == "timed_out" and result["exit_code"] != 0
    assert time.monotonic() - started < 3


def test_python_cancellation_reaps_process(monkeypatch):
    original = asyncio.create_subprocess_exec
    processes = []
    async def track(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", track)
    async def check():
        task = asyncio.create_task(run_python("import time; time.sleep(60)"))
        while not processes:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes[0].returncode is not None
        assert not Path(f"/proc/{processes[0].pid}").exists()
    asyncio.run(check())


@pytest.mark.parametrize("name", ["../private", "/etc/passwd", "a/../../private", "main.py", "main.py/helper", "a//b", "a\\b"])
def test_python_rejects_unsafe_input_paths(name):
    result = asyncio.run(run_python("print('hello')", {name: "data"}))
    assert result["status"] == "error" and "relative paths" in result["error"]


def test_python_does_not_fall_back_without_sandbox(monkeypatch):
    monkeypatch.setattr("company.python_runner.shutil.which", lambda _: None)
    result = asyncio.run(run_python("print('must not execute')"))
    assert result["status"] == "error" and "requires" in result["error"]
    assert "stdout" not in result
