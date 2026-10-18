"""Execute a project snapshot inside tmpfs and return validated text artifacts."""

import asyncio
import json
from pathlib import PurePosixPath

from company.python_runner import POLICY, sandbox_command

MAX_FILES = 128
MAX_BYTES = 4 * 1024 * 1024


def project_path(path: str) -> str:
    if not isinstance(path, str):
        raise ValueError("Use a project-relative file path")
    if path.startswith("/work/"):
        path = path[6:]
    if (not path or len(path) > 200 or PurePosixPath(path).is_absolute()
            or any(part in ("", ".", "..") for part in path.split("/")) or "\\" in path or "\x00" in path):
        raise ValueError("Use a project-relative path without traversal; only /work is accessible")
    return path


def validate_files(files: dict) -> dict:
    if not isinstance(files, dict) or len(files) > MAX_FILES:
        raise ValueError(f"Project supports at most {MAX_FILES} text files")
    size = 0
    for name, content in files.items():
        if project_path(name) != name or not isinstance(content, str):
            raise ValueError("Project snapshots require relative paths and text contents")
        encoded = content.encode("utf-8")
        if len(encoded) > POLICY["file_bytes"]:
            raise ValueError("Project file exceeds 1 MiB")
        size += len(encoded)
        if any(str(parent) in files for parent in PurePosixPath(name).parents if str(parent) != "."):
            raise ValueError("A project path cannot be both a file and a directory")
    if size > MAX_BYTES:
        raise ValueError("Project exceeds 4 MiB of text files")
    return dict(files)


WORKER = r'''
import ast, json, pathlib, resource, sys, types
p = json.load(sys.stdin)
for kind, value in ((resource.RLIMIT_CPU, p['limits']['cpu_seconds']),
                    (resource.RLIMIT_AS, p['limits']['memory_bytes']),
                    (resource.RLIMIT_FSIZE, p['limits']['file_bytes']),
                    (resource.RLIMIT_NPROC, 0), (resource.RLIMIT_NOFILE, 64), (resource.RLIMIT_CORE, 0)):
    resource.setrlimit(kind, (value, value))
sys.stdin.close()
sys.stdin = open('/dev/null')
sys.dont_write_bytecode = True
path = '/work/' + p['file_path']
sys.argv = [path, *p['args']]
sys.path[:0] = [str(pathlib.Path(path).parent), '/work']
module = types.ModuleType('__main__')
module.__file__ = path
module.__dict__['__python_tool_display__'] = sys.displayhook
sys.modules['__main__'] = module
tree = ast.parse(pathlib.Path(path).read_text(), filename=path)
if tree.body and isinstance(tree.body[-1], ast.Expr):
    expression = tree.body[-1]
    expression.value = ast.Call(func=ast.Name(id='__python_tool_display__', ctx=ast.Load()), args=[expression.value], keywords=[])
exec(compile(ast.fix_missing_locations(tree), path, 'exec'), module.__dict__)
'''

# This supervisor is a separate process from generated code. It lives entirely
# inside the sandbox, drains bounded logs, then exports regular UTF-8 files.
# The controller validates the export again; no host directory is mounted.
SUPERVISOR = r'''
import json, os, pathlib, stat, subprocess, sys, threading
p = json.load(sys.stdin)
for name, content in p['files'].items():
    path = pathlib.Path('/work') / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
process = subprocess.Popen(['/usr/bin/python3', '-I', '-S', '-u', '-c', p['worker']],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
logs = {}
def drain(name, stream):
    saved, total = bytearray(), 0
    while chunk := stream.read(8192):
        total += len(chunk)
        saved.extend(chunk[:max(0, p['limits']['output_bytes_per_stream'] - len(saved))])
    logs[name] = saved.decode('utf-8', errors='replace')
    logs[name + '_truncated'] = total > len(saved)
readers = [threading.Thread(target=drain, args=(name, stream)) for name, stream in
           (('stdout', process.stdout), ('stderr', process.stderr))]
for reader in readers: reader.start()
process.stdin.write(json.dumps({'file_path': p['file_path'], 'args': p['args'], 'limits': p['limits']}).encode())
process.stdin.close()
code = process.wait()
for reader in readers: reader.join()
result = {'status': 'ok' if code == 0 else 'error', 'exit_code': code, **logs}
try:
    files, total, entries = {}, 0, 0
    for root, dirs, names in os.walk('/work', followlinks=False):
        entries += len(dirs) + len(names)
        if entries > 2048: raise ValueError('Too many filesystem entries')
        for name in dirs + names:
            path = pathlib.Path(root) / name
            info = path.lstat()
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise ValueError('Only regular files and directories can persist')
        dirs[:] = [name for name in dirs if name != '__pycache__']
        for name in names:
            if name.endswith('.pyc'): continue
            path = pathlib.Path(root) / name
            if path.stat().st_size > p['limits']['file_bytes']: raise ValueError('File exceeds 1 MiB')
            content = path.read_bytes()
            total += len(content)
            if len(files) >= p['max_files'] or total > p['max_bytes']: raise ValueError('Project snapshot exceeds limits')
            files[str(path.relative_to('/work'))] = content.decode('utf-8')
    result['files'] = files
except (OSError, ValueError) as error:
    result.update(status='error', persistence_error=str(error))
print(json.dumps(result))
'''


async def run_project(files: dict, file_path: str, args: list[str] | None = None) -> dict:
    files = validate_files(files)
    file_path = project_path(file_path)
    if file_path not in files:
        raise ValueError("File does not exist; use project_list and project_write first")
    args = [] if args is None else args
    if not isinstance(args, list) or len(args) > 32 or any(not isinstance(arg, str) or len(arg) > 1000 for arg in args):
        raise ValueError("Use at most 32 short string arguments")
    command = sandbox_command(bootstrap=SUPERVISOR)
    process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE,
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                 env={"PATH": "/usr/bin"}, close_fds=True)
    async def drain(stream, limit):
        saved, total = bytearray(), 0
        while chunk := await stream.read(8192):
            total += len(chunk)
            saved.extend(chunk[:max(0, limit - len(saved))])
        return bytes(saved), total > limit
    async def feed():
        try:
            process.stdin.write(json.dumps({"files": files, "file_path": file_path, "args": args, "worker": WORKER,
                                           "limits": POLICY, "max_files": MAX_FILES, "max_bytes": MAX_BYTES}).encode())
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            process.stdin.close()
    readers = [asyncio.create_task(drain(process.stdout, MAX_BYTES * 6 + 100000)),
               asyncio.create_task(drain(process.stderr, 4000))]
    writer = asyncio.create_task(feed())
    timed_out = False
    try:
        await asyncio.wait_for(process.wait(), timeout=POLICY["wall_seconds"])
    except TimeoutError:
        timed_out = True
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()
        await writer
        (raw, truncated), (stderr, _) = await asyncio.gather(*readers)
    if timed_out:
        return {"status": "timed_out", "error": "Python exceeded 10 seconds; saved project files are unchanged"}
    if process.returncode != 0 or truncated:
        return {"status": "error", "error": "Sandbox did not return a complete project snapshot", "stderr": stderr.decode(errors="replace")}
    try:
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get("status") not in ("ok", "error"):
            raise ValueError("Invalid result")
        if "files" in result:
            result["files"] = validate_files(result["files"])
        return result
    except (ValueError, TypeError):
        return {"status": "error", "error": "Sandbox returned invalid project artifacts; saved files are unchanged"}
