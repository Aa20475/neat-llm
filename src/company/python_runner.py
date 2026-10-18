"""Disposable Linux Python execution; never fall back to unsandboxed execution."""

import asyncio
import json
from pathlib import Path, PurePosixPath
import shutil


POLICY = {
    "backend": "bubblewrap",
    "workspace": "fresh_per_call",
    "network": False,
    "wall_seconds": 10,
    "cpu_seconds": 5,
    "memory_bytes": 256 * 1024 * 1024,
    "workspace_bytes": 16 * 1024 * 1024,
    "file_bytes": 1024 * 1024,
    "output_bytes_per_stream": 4000,
}

# This bootstrap runs INSIDE the namespace, before any generated code. Limits
# are hard limits; generated code cannot raise them again. No preexec_fn is used
# in the multithreaded viewer. The system interpreter uses -I -S (stdlib only).
BOOTSTRAP = r"""
import ast, json, pathlib, resource, sys, types
p = json.load(sys.stdin)
limits = p['limits']
for kind, value in (
    (resource.RLIMIT_CPU, limits['cpu_seconds']),
    (resource.RLIMIT_AS, limits['memory_bytes']),
    (resource.RLIMIT_FSIZE, limits['file_bytes']),
    (resource.RLIMIT_NPROC, 0),
    (resource.RLIMIT_NOFILE, 64),
    (resource.RLIMIT_CORE, 0),
):
    resource.setrlimit(kind, (value, value))
for name, content in p['files'].items():
    path = pathlib.Path('/work') / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
pathlib.Path('/work/main.py').write_text(p['code'], encoding='utf-8')
sys.stdin.close()
sys.stdin = open('/dev/null')
sys.argv = ['/work/main.py']
sys.path.insert(0, '/work')
module = types.ModuleType('__main__')
module.__file__ = '/work/main.py'
module.__dict__['__python_tool_display__'] = sys.displayhook
sys.modules['__main__'] = module
tree = ast.parse(p['code'], filename='/work/main.py')
if tree.body and isinstance(tree.body[-1], ast.Expr):
    expression = tree.body[-1]
    expression.value = ast.Call(func=ast.Name(id='__python_tool_display__', ctx=ast.Load()),
                                args=[expression.value], keywords=[])
exec(compile(ast.fix_missing_locations(tree), '/work/main.py', 'exec'), module.__dict__)
"""


def sandbox_command() -> list[str]:
    bwrap = shutil.which("bwrap")
    if not bwrap or not Path("/usr/bin/python3").is_file():
        raise RuntimeError("Python execution requires Linux, bubblewrap, and /usr/bin/python3")
    command = [
        bwrap, "--unshare-all", "--unshare-user", "--disable-userns",
        "--die-with-parent", "--new-session", "--cap-drop", "ALL",
        "--ro-bind", "/usr", "/usr",
    ]
    # Support both merged-/usr and distributions with separate loader paths.
    for name in ("lib", "lib64"):
        path = Path("/") / name
        if path.is_symlink():
            command += ["--symlink", str(path.readlink()), str(path)]
        elif path.is_dir():
            command += ["--ro-bind", str(path), str(path)]
    command += [
        "--proc", "/proc", "--remount-ro", "/proc",
        "--dev", "/dev", "--remount-ro", "/dev",
        "--size", str(POLICY["workspace_bytes"]), "--tmpfs", "/work",
        "--symlink", "work", "/tmp", "--chdir", "/work",
        "--remount-ro", "/", "--clearenv",
        "--setenv", "PATH", "/usr/bin", "--setenv", "LANG", "C.UTF-8",
        "--setenv", "TMPDIR", "/work",
        "--", "/usr/bin/python3", "-I", "-S", "-u", "-c", BOOTSTRAP,
    ]
    return command


def validate_input(code: str, files: dict[str, str] | None) -> dict[str, str]:
    if not isinstance(code, str) or not code.strip() or len(code.encode()) > 32000:
        raise ValueError("Supply nonempty Python source, at most 32,000 bytes")
    files = {} if files is None else files
    if not isinstance(files, dict) or len(files) > 12:
        raise ValueError("Supply at most 12 text input files")
    total = 0
    for name, content in files.items():
        if not isinstance(name, str) or not isinstance(content, str):
            raise ValueError("File names and contents must be strings")
        path = PurePosixPath(name)
        if (not name or len(name) > 200 or path.is_absolute() or
                any(part in ("", ".", "..") for part in name.split("/")) or
                "\\" in name or "\x00" in name or path.parts[0] == "main.py"):
            raise ValueError("Input files need relative paths without traversal; main.py is reserved")
        total += len(content.encode())
    if total > 64000:
        raise ValueError("Input files exceed the 64,000-byte total limit")
    return files


async def run_python(code: str, files: dict[str, str] | None = None) -> dict:
    """Write code and inputs in a new tmpfs; return bounded stdout/stderr."""
    try:
        files = validate_input(code, files)
        command = sandbox_command()
    except (ValueError, RuntimeError) as error:
        return {"status": "error", "error": str(error)}

    try:
        process = await asyncio.create_subprocess_exec(
            *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env={"PATH": "/usr/bin"}, close_fds=True,
        )
    except OSError:
        return {"status": "unavailable", "error": "Unable to start the Python sandbox; no code was executed"}

    async def capture(stream):
        saved, total = bytearray(), 0
        while chunk := await stream.read(8192):
            total += len(chunk)
            saved.extend(chunk[:max(0, POLICY["output_bytes_per_stream"] - len(saved))])
        return saved.decode("utf-8", errors="replace"), total > len(saved)

    async def feed():
        try:
            process.stdin.write(json.dumps({"code": code, "files": files, "limits": POLICY}).encode())
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            process.stdin.close()

    readers = [asyncio.create_task(capture(process.stdout)), asyncio.create_task(capture(process.stderr))]
    writer = asyncio.create_task(feed())
    timed_out = False
    try:
        await asyncio.wait_for(process.wait(), timeout=POLICY["wall_seconds"])
    except TimeoutError:
        timed_out = True
    finally:
        # Killing bwrap kills the PID namespace and all its processes, including
        # when a run is cancelled. Nothing survives to write after a tool returns.
        if process.returncode is None:
            process.kill()
        await process.wait()
        await writer
        (stdout, out_cut), (stderr, err_cut) = await asyncio.gather(*readers)
    return {
        "status": "timed_out" if timed_out else "ok" if process.returncode == 0 else "error",
        "exit_code": process.returncode, "stdout": stdout, "stderr": stderr,
        "stdout_truncated": out_cut, "stderr_truncated": err_cut,
        **({"note": "No output was produced. Print the result or end with an expression; do not infer an unseen result."}
           if process.returncode == 0 and not stdout and not stderr else {}),
    }
