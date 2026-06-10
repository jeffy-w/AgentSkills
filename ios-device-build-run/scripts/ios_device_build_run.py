#!/usr/bin/env python3
"""Build, install, run, and inspect iOS apps on physical devices."""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import plistlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

BASE_DIR = Path.home() / ".codex" / "ios-device-build-run"
SESSIONS_DIR = BASE_DIR / "sessions"
LATEST_FILE = BASE_DIR / "latest-session"
LOG_NAMES = {
    "build": ["build.raw.log"],
    "pretty": ["build.pretty.log"],
    "run": ["run.log", "devicectl-launch.log"],
    "device": ["device.log"],
}


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def eprint(*items: object) -> None:
    print(*items, file=sys.stderr)


def ensure_base() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def run_capture(cmd: list[str], cwd: Path | None = None, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None




def parse_json_from_output(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        starts = [i for i, ch in enumerate(text) if ch in "[{"]
        for start in starts:
            try:
                value, _ = decoder.raw_decode(text[start:])
                return value
            except json.JSONDecodeError:
                continue
        raise

def sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.")
    return cleaned or "ios-app"


def create_session(label: str | None = None) -> Path:
    ensure_base()
    suffix = sanitize_name(label or "session")
    session = SESSIONS_DIR / f"{now_stamp()}-{suffix}"
    idx = 1
    while session.exists():
        session = SESSIONS_DIR / f"{now_stamp()}-{suffix}-{idx}"
        idx += 1
    session.mkdir(parents=True)
    LATEST_FILE.write_text(str(session), encoding="utf-8")
    write_json(session / "pids.json", {})
    return session


def resolve_session(value: str | None, create: bool = False, label: str | None = None) -> Path:
    ensure_base()
    if create:
        return create_session(label)
    if not value or value == "latest":
        if not LATEST_FILE.exists():
            raise SystemExit("No latest session exists. Run build/build-run first or pass --session <path>.")
        session = Path(LATEST_FILE.read_text(encoding="utf-8").strip())
    else:
        candidate = Path(value).expanduser()
        session = candidate if candidate.is_absolute() else SESSIONS_DIR / value
    if not session.exists():
        raise SystemExit(f"Session not found: {session}")
    return session


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def append_event(session: Path, event: str, data: dict[str, Any] | None = None) -> None:
    line = {"time": dt.datetime.now().isoformat(timespec="seconds"), "event": event, "data": data or {}}
    with (session / "events.jsonl").open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(line, ensure_ascii=False) + "\n")


def tee_process(cmd: list[str], raw_log: Path, pretty_log: Path | None = None, cwd: Path | None = None, beautify: bool = False, renderer: str = "terminal") -> int:
    raw_log.parent.mkdir(parents=True, exist_ok=True)
    pretty_proc: subprocess.Popen[str] | None = None
    pretty_stdin = None
    pretty_fp = None
    if beautify and command_exists("xcbeautify"):
        pretty_fp = pretty_log.open("w", encoding="utf-8", errors="replace") if pretty_log else subprocess.DEVNULL
        pretty_proc = subprocess.Popen(["xcbeautify", "--renderer", renderer], stdin=subprocess.PIPE, stdout=pretty_fp, stderr=subprocess.STDOUT, text=True)
        pretty_stdin = pretty_proc.stdin
    env = os.environ.copy()
    env.setdefault("NSUnbufferedIO", "YES")
    with raw_log.open("w", encoding="utf-8", errors="replace") as raw_fp:
        raw_fp.write("$ " + shlex.join(cmd) + "\n")
        raw_fp.flush()
        proc = subprocess.Popen(cmd, cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
        assert proc.stdout is not None
        for line in proc.stdout:
            raw_fp.write(line)
            raw_fp.flush()
            if pretty_stdin:
                try:
                    pretty_stdin.write(line)
                    pretty_stdin.flush()
                except BrokenPipeError:
                    pretty_stdin = None
            elif not beautify:
                print(line, end="")
        code = proc.wait()
    if pretty_stdin:
        pretty_stdin.close()
    if pretty_proc:
        pretty_proc.wait(timeout=30)
    if pretty_fp and hasattr(pretty_fp, "close"):
        pretty_fp.close()
    if beautify and pretty_log and pretty_log.exists():
        tail_file(pretty_log, 200)
    return code


def tail_file(path: Path, n: int) -> None:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-n:]:
        print(line)


def find_repo_root(start: Path) -> Path:
    current = start.resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists() or list(parent.glob("*.xcworkspace")) or list(parent.glob("*.xcodeproj")):
            return parent
    return current


def project_name_candidates(root: Path) -> list[str]:
    names: list[str] = []
    names.append(root.name)
    for ws in sorted(root.glob("*.xcworkspace")):
        names.append(ws.stem)
    for proj in sorted(root.glob("*.xcodeproj")):
        names.append(proj.stem)
    out: list[str] = []
    for name in names:
        if name not in out:
            out.append(name)
    return out


def choose_workspace_or_project(root: Path, workspace: str | None, project: str | None) -> tuple[str, Path]:
    if workspace and project:
        raise SystemExit("Pass either --workspace or --project, not both.")
    if workspace:
        return "workspace", (root / workspace).resolve() if not Path(workspace).is_absolute() else Path(workspace)
    if project:
        return "project", (root / project).resolve() if not Path(project).is_absolute() else Path(project)
    workspaces = sorted(root.glob("*.xcworkspace"))
    projects = sorted(root.glob("*.xcodeproj"))
    for candidate in project_name_candidates(root):
        match = root / f"{candidate}.xcworkspace"
        if match.exists():
            return "workspace", match
    if len(workspaces) == 1:
        return "workspace", workspaces[0]
    for candidate in project_name_candidates(root):
        match = root / f"{candidate}.xcodeproj"
        if match.exists():
            return "project", match
    if len(projects) == 1:
        return "project", projects[0]
    choices = [p.name for p in workspaces + projects]
    raise SystemExit("Cannot choose workspace/project. Pass --workspace or --project. Candidates: " + ", ".join(choices))


def xcodebuild_base(kind: str, container: Path, scheme: str | None = None, configuration: str | None = None, destination: str | None = None, derived_data: Path | None = None) -> list[str]:
    cmd = ["xcodebuild", f"-{kind}", str(container)]
    if scheme:
        cmd += ["-scheme", scheme]
    if configuration:
        cmd += ["-configuration", configuration]
    if destination:
        cmd += ["-destination", destination]
    if derived_data:
        cmd += ["-derivedDataPath", str(derived_data)]
    return cmd


def list_schemes(root: Path, kind: str, container: Path) -> list[str]:
    cp = run_capture(["xcodebuild", "-list", f"-{kind}", str(container), "-json"], cwd=root, timeout=120)
    if cp.returncode != 0:
        raise SystemExit("xcodebuild -list failed:\n" + cp.stdout[-4000:])
    data = parse_json_from_output(cp.stdout)
    section = data.get("workspace") or data.get("project") or {}
    return section.get("schemes") or []


def choose_scheme(root: Path, kind: str, container: Path, scheme: str | None) -> str:
    if scheme:
        return scheme
    schemes = list_schemes(root, kind, container)
    preferred = [container.stem, *project_name_candidates(root)]
    for name in preferred:
        if name in schemes:
            return name
    if len(schemes) == 1:
        return schemes[0]
    raise SystemExit("Cannot choose scheme. Pass --scheme. Candidates: " + ", ".join(schemes))


def show_build_settings(root: Path, kind: str, container: Path, scheme: str, configuration: str, destination: str, derived_data: Path, session: Path) -> list[dict[str, Any]]:
    out = session / "build-settings.json"
    cmd = xcodebuild_base(kind, container, scheme, configuration, destination, derived_data) + ["-showBuildSettings", "-json"]
    cp = run_capture(cmd, cwd=root, timeout=180)
    out.write_text(cp.stdout, encoding="utf-8", errors="replace")
    if cp.returncode != 0:
        raise SystemExit("xcodebuild -showBuildSettings failed:\n" + cp.stdout[-4000:])
    return parse_json_from_output(cp.stdout)


def locate_app(settings: list[dict[str, Any]], derived_data: Path) -> Path:
    candidates: list[Path] = []
    for target in settings:
        bs = target.get("buildSettings", {})
        built = bs.get("BUILT_PRODUCTS_DIR")
        wrapper = bs.get("WRAPPER_NAME") or bs.get("FULL_PRODUCT_NAME")
        product_type = bs.get("PRODUCT_TYPE", "")
        if built and wrapper and (str(wrapper).endswith(".app") or product_type.endswith("application")):
            p = Path(built) / wrapper
            if p.exists():
                candidates.append(p)
    if not candidates:
        candidates = [p for p in derived_data.rglob("*.app") if p.is_dir()]
    app_candidates = [p for p in candidates if (p / "Info.plist").exists()]
    if len(app_candidates) == 1:
        return app_candidates[0]
    if not app_candidates:
        raise SystemExit(f"No .app found under {derived_data}")
    raise SystemExit("Multiple .app candidates found; pass --app-path:\n" + "\n".join(str(p) for p in app_candidates))


def read_bundle_id(app_path: Path) -> str:
    info = app_path / "Info.plist"
    with info.open("rb") as fp:
        plist = plistlib.load(fp)
    bundle_id = plist.get("CFBundleIdentifier")
    if not bundle_id:
        raise SystemExit(f"CFBundleIdentifier not found in {info}")
    return str(bundle_id)


def list_physical_devices_json(tmp: Path) -> list[dict[str, Any]]:
    # Prefer xcdevice because its JSON is a simple array and avoids devicectl's
    # nested CoreDevice objects, which can otherwise produce duplicate rows.
    cp2 = run_capture(["xcrun", "xcdevice", "list"], timeout=60)
    try:
        data = parse_json_from_output(cp2.stdout)
        physical = [
            d for d in data
            if not d.get("simulator")
            and d.get("available")
            and not d.get("ignored")
            and str(d.get("platform", "")).endswith("iphoneos")
        ]
        if physical:
            return physical
    except Exception:
        pass

    json_path = tmp / "devices.json"
    log_path = tmp / "devices.log"
    cp = run_capture(["xcrun", "devicectl", "list", "devices", "--json-output", str(json_path), "--log-output", str(log_path)], timeout=60)
    if cp.returncode == 0 and json_path.exists():
        data = read_json(json_path, {})
        devices = extract_devices(data)
        seen: set[str] = set()
        physical: list[dict[str, Any]] = []
        for d in devices:
            ident = device_identifier(d)
            if ident and ident not in seen and is_physical_available(d):
                seen.add(ident)
                physical.append(d)
        return physical
    return []


def extract_devices(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if any(k in value for k in ("identifier", "name", "deviceProperties", "hardwareProperties")):
            found.append(value)
        for child in value.values():
            found.extend(extract_devices(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(extract_devices(child))
    return found


def is_physical_available(device: dict[str, Any]) -> bool:
    text = json.dumps(device, ensure_ascii=False).lower()
    if "simulator" in text or "iphonesimulator" in text:
        return False
    if "iphoneos" not in text and "iphone" not in text and "ipad" not in text:
        return False
    return "available" in text or device.get("available") is True


def device_identifier(device: dict[str, Any]) -> str | None:
    for key in ("identifier", "udid", "UDID", "serialNumber", "ecid"):
        if device.get(key):
            return str(device[key])
    props = device.get("deviceProperties") or device.get("hardwareProperties") or {}
    for key in ("identifier", "udid", "serialNumber"):
        if props.get(key):
            return str(props[key])
    return None


def device_name(device: dict[str, Any]) -> str:
    return str(device.get("name") or device.get("deviceProperties", {}).get("name") or device.get("modelName") or "")


def device_interface(device: dict[str, Any]) -> str:
    value = device.get("interface")
    if value:
        return str(value).lower()
    text = json.dumps(device, ensure_ascii=False).lower()
    if "usb" in text:
        return "usb"
    if "network" in text or "wifi" in text or "wi-fi" in text:
        return "network"
    return "unknown"


def is_wired_device(device: dict[str, Any]) -> bool:
    return device_interface(device) in {"usb", "wired", "direct"}


def format_device_candidate(device: dict[str, Any]) -> str:
    ident = device_identifier(device) or "?"
    name = device_name(device)
    iface = device_interface(device)
    return f"{ident}\t{name}\tinterface={iface}"


def choose_device(device: str | None, session: Path) -> str:
    if device:
        return device
    devices = list_physical_devices_json(session)
    devices = [d for d in devices if device_identifier(d)]
    if not devices:
        raise SystemExit("No available physical iOS device found. Connect/unlock a device or pass --device.")

    wired = [d for d in devices if is_wired_device(d)]
    if len(wired) == 1:
        return device_identifier(wired[0])  # type: ignore[return-value]
    if len(wired) > 1:
        raise SystemExit("Multiple wired physical devices found; pass --device. Wired candidates:\n" + "\n".join(format_device_candidate(d) for d in wired))

    if len(devices) == 1:
        return device_identifier(devices[0])  # type: ignore[return-value]

    raise SystemExit(
        "Multiple physical devices found and none is wired; pass --device or connect exactly one device by USB. Candidates:\n"
        + "\n".join(format_device_candidate(d) for d in devices)
    )


def save_metadata(session: Path, updates: dict[str, Any]) -> None:
    meta = read_json(session / "metadata.json", {})
    meta.update(updates)
    meta["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    write_json(session / "metadata.json", meta)


def cmd_doctor(args: argparse.Namespace) -> int:
    tools = ["xcodebuild", "xcrun", "idevicesyslog", "xcbeautify"]
    for tool in tools:
        path = shutil.which(tool)
        status = "OK" if path else ("OPTIONAL-MISSING" if tool in {"idevicesyslog", "xcbeautify"} else "MISSING")
        print(f"{status}\t{tool}\t{path or ''}")
    session = create_session("doctor")
    devices = list_physical_devices_json(session)
    print(f"devices\t{len(devices)} available physical device(s)")
    for d in devices:
        print(f"device\t{format_device_candidate(d)}")
    return 0


def cmd_devices(args: argparse.Namespace) -> int:
    session = create_session("devices")
    devices = list_physical_devices_json(session)
    for d in devices:
        print(json.dumps({"id": device_identifier(d), "name": device_name(d), "model": d.get("modelName"), "os": d.get("operatingSystemVersion"), "interface": device_interface(d), "wired": is_wired_device(d)}, ensure_ascii=False))
    return 0


def prepare_build(args: argparse.Namespace, create: bool = True) -> tuple[Path, Path, str, Path, str, str, str, Path]:
    root = find_repo_root(Path(args.cwd or os.getcwd()))
    kind, container = choose_workspace_or_project(root, args.workspace, args.project)
    scheme = choose_scheme(root, kind, container, args.scheme)
    configuration = args.configuration or "Debug"
    destination = args.destination or "generic/platform=iOS"
    session = resolve_session(args.session, create=create, label=scheme) if create else resolve_session(args.session)
    derived_data = Path(args.derived_data).expanduser() if args.derived_data else session / "DerivedData"
    save_metadata(session, {"root": str(root), "container_kind": kind, "container": str(container), "scheme": scheme, "configuration": configuration, "destination": destination, "derived_data": str(derived_data)})
    return session, root, kind, container, scheme, configuration, destination, derived_data


def cmd_build(args: argparse.Namespace) -> int:
    session, root, kind, container, scheme, configuration, destination, derived_data = prepare_build(args, create=True)
    settings = show_build_settings(root, kind, container, scheme, configuration, destination, derived_data, session)
    cmd = xcodebuild_base(kind, container, scheme, configuration, destination, derived_data) + ["build"]
    if args.extra_xcodebuild_arg:
        cmd += args.extra_xcodebuild_arg
    beautify = args.beautify == "always" or (args.beautify == "auto" and command_exists("xcbeautify"))
    append_event(session, "build_started", {"cmd": cmd})
    code = tee_process(cmd, session / "build.raw.log", session / "build.pretty.log", cwd=root, beautify=beautify, renderer=args.xcbeautify_renderer)
    append_event(session, "build_finished", {"exit_code": code})
    save_metadata(session, {"build_exit_code": code})
    if code == 0:
        app = locate_app(settings, derived_data)
        bundle_id = read_bundle_id(app)
        save_metadata(session, {"app_path": str(app), "bundle_id": bundle_id})
        print(f"SESSION={session}")
        print(f"APP_PATH={app}")
        print(f"BUNDLE_ID={bundle_id}")
    else:
        print(f"SESSION={session}")
    return code


def install_app(session: Path, device: str, app_path: Path) -> int:
    json_path = session / "install.json"
    log_path = session / "install.log"
    cmd = ["xcrun", "devicectl", "device", "install", "app", "--device", device, str(app_path), "--json-output", str(json_path), "--log-output", str(log_path)]
    append_event(session, "install_started", {"cmd": cmd})
    cp = run_capture(cmd, timeout=300)
    (session / "install.stdout.log").write_text(cp.stdout, encoding="utf-8", errors="replace")
    append_event(session, "install_finished", {"exit_code": cp.returncode})
    return cp.returncode


def cmd_install(args: argparse.Namespace) -> int:
    session = resolve_session(args.session)
    meta = read_json(session / "metadata.json", {})
    app_path = Path(args.app_path or meta.get("app_path") or "").expanduser()
    if not app_path.exists():
        raise SystemExit("App path not found. Pass --app-path or run build first.")
    device = choose_device(args.device, session)
    code = install_app(session, device, app_path)
    save_metadata(session, {"device": device, "app_path": str(app_path), "install_exit_code": code})
    return code


def start_log_stream(session: Path, device: str, bundle_id: str | None, process: str | None = None, duration: int | None = None) -> int | None:
    log_file = session / "device.log"
    if command_exists("idevicesyslog"):
        cmd = ["idevicesyslog", "--udid", device, "--no-colors", "--output", str(log_file)]
        if process:
            cmd += ["--process", process]
        elif bundle_id:
            cmd += ["--match", bundle_id]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        pids = read_json(session / "pids.json", {})
        pids["device_log"] = {"pid": proc.pid, "cmd": cmd, "started_at": dt.datetime.now().isoformat(timespec="seconds")}
        write_json(session / "pids.json", pids)
        append_event(session, "log_stream_started", {"pid": proc.pid, "cmd": cmd, "duration": duration})
        if duration:
            stopper = subprocess.Popen([sys.executable, __file__, "stop-log", "--session", str(session), "--delay", str(duration)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            pids["device_log_stopper"] = {"pid": stopper.pid, "duration": duration}
            write_json(session / "pids.json", pids)
        return proc.pid
    append_event(session, "log_stream_unavailable", {"reason": "idevicesyslog not found"})
    eprint("idevicesyslog not found; device.log unavailable. Install libimobiledevice or rely on run.log.")
    return None


def launch_app(session: Path, device: str, bundle_id: str, args: argparse.Namespace) -> int:
    json_path = session / "launch.json"
    log_path = session / "devicectl-launch.log"
    cmd = ["xcrun", "devicectl", "device", "process", "launch", "--device", device]
    if not args.no_terminate_existing:
        cmd.append("--terminate-existing")
    if args.console:
        cmd.append("--console")
    cmd += ["--json-output", str(json_path), "--log-output", str(log_path), bundle_id]
    if args.app_argument:
        cmd += args.app_argument
    append_event(session, "launch_started", {"cmd": cmd})
    timeout = None if args.console else args.launch_timeout
    cp = run_capture(cmd, timeout=timeout)
    (session / "run.log").write_text("$ " + shlex.join(cmd) + "\n" + cp.stdout, encoding="utf-8", errors="replace")
    append_event(session, "launch_finished", {"exit_code": cp.returncode})
    save_metadata(session, {"launch_exit_code": cp.returncode})
    return cp.returncode


def cmd_run(args: argparse.Namespace) -> int:
    session = resolve_session(args.session)
    meta = read_json(session / "metadata.json", {})
    bundle_id = args.bundle_id or meta.get("bundle_id")
    if not bundle_id:
        raise SystemExit("Bundle id missing. Pass --bundle-id or run build first.")
    device = choose_device(args.device or meta.get("device"), session)
    save_metadata(session, {"device": device, "bundle_id": bundle_id})
    if args.start_log:
        start_log_stream(session, device, bundle_id, args.process_name, args.log_duration)
        time.sleep(1)
    return launch_app(session, device, bundle_id, args)


def cmd_build_run(args: argparse.Namespace) -> int:
    code = cmd_build(args)
    if code != 0:
        return code
    session = resolve_session(args.session or "latest")
    meta = read_json(session / "metadata.json", {})
    device = choose_device(args.device, session)
    app_path = Path(args.app_path or meta.get("app_path"))
    bundle_id = args.bundle_id or meta.get("bundle_id") or read_bundle_id(app_path)
    install_code = install_app(session, device, app_path)
    save_metadata(session, {"device": device, "install_exit_code": install_code})
    if install_code != 0:
        return install_code
    start_log_stream(session, device, bundle_id, args.process_name, args.log_duration)
    time.sleep(1)
    return launch_app(session, device, bundle_id, args)


def cmd_log_stream(args: argparse.Namespace) -> int:
    session = resolve_session(args.session)
    meta = read_json(session / "metadata.json", {})
    device = choose_device(args.device or meta.get("device"), session)
    bundle_id = args.bundle_id or meta.get("bundle_id")
    start_log_stream(session, device, bundle_id, args.process_name, args.log_duration)
    return 0


def stop_pid(pid: int) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return False


def cmd_stop_log(args: argparse.Namespace) -> int:
    if args.delay:
        time.sleep(args.delay)
    session = resolve_session(args.session)
    pids = read_json(session / "pids.json", {})
    entry = pids.get("device_log") or {}
    pid = entry.get("pid")
    if pid:
        stopped = stop_pid(int(pid))
        append_event(session, "log_stream_stopped", {"pid": pid, "stopped": stopped})
        pids.pop("device_log", None)
        write_json(session / "pids.json", pids)
        print(f"stopped pid {pid}: {stopped}")
    else:
        print("no device_log pid recorded")
    return 0


def iter_log_files(session: Path, file_key: str) -> list[Path]:
    if file_key == "all":
        keys = ["build", "pretty", "run", "device"]
    else:
        keys = [file_key]
    paths: list[Path] = []
    for key in keys:
        for name in LOG_NAMES.get(key, []):
            p = session / name
            if p.exists():
                paths.append(p)
    return paths


def parse_since(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        raise SystemExit("--since must be ISO-like timestamp, e.g. 2026-06-10T18:00:00")


def line_matches_since(line: str, since: dt.datetime | None) -> bool:
    if since is None:
        return True
    m = re.search(r"(20\d\d[-/]\d\d[-/]\d\d[ T]\d\d:\d\d:\d\d)", line)
    if not m:
        return True
    text = m.group(1).replace("/", "-")
    try:
        return dt.datetime.fromisoformat(text) >= since
    except ValueError:
        return True


def filter_lines(lines: list[str], args: argparse.Namespace) -> list[tuple[int, str]]:
    flags = re.IGNORECASE if args.ignore_case else 0
    grep = args.grep.lower() if args.grep and args.ignore_case else args.grep
    regex = re.compile(args.search, flags) if args.search else None
    since = parse_since(args.since)
    matched: list[int] = []
    for idx, line in enumerate(lines):
        if not line_matches_since(line, since):
            continue
        hay = line.lower() if args.ignore_case else line
        ok = True
        if grep:
            ok = grep in hay
        if ok and regex:
            ok = bool(regex.search(line))
        if ok:
            matched.append(idx)
    if args.context and matched:
        expanded: set[int] = set()
        for idx in matched:
            for i in range(max(0, idx - args.context), min(len(lines), idx + args.context + 1)):
                expanded.add(i)
        matched = sorted(expanded)
    return [(i + 1, lines[i]) for i in matched]


def cmd_logs(args: argparse.Namespace) -> int:
    session = resolve_session(args.session)
    paths = iter_log_files(session, args.file)
    if not paths:
        raise SystemExit(f"No log files for --file {args.file} in {session}")
    max_lines = args.max_lines
    for path in paths:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if args.tail:
            lines = lines[-args.tail:]
            base = max(0, len(path.read_text(encoding="utf-8", errors="replace").splitlines()) - len(lines))
        else:
            base = 0
        filtered = filter_lines(lines, args)
        if max_lines and len(filtered) > max_lines:
            filtered = filtered[-max_lines:]
        print(f"--- {path} ({len(filtered)} line(s)) ---")
        for no, line in filtered:
            prefix = f"{base + no}:" if args.line_numbers else ""
            print(prefix + line)
    return 0


def cmd_sessions(args: argparse.Namespace) -> int:
    ensure_base()
    sessions = sorted([p for p in SESSIONS_DIR.iterdir() if p.is_dir()], reverse=True)
    for p in sessions[: args.limit]:
        meta = read_json(p / "metadata.json", {})
        latest = " *latest" if LATEST_FILE.exists() and LATEST_FILE.read_text(encoding="utf-8").strip() == str(p) else ""
        print(f"{p.name}{latest}\t{meta.get('scheme','')}\t{meta.get('bundle_id','')}\t{p}")
    return 0


def add_build_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cwd")
    parser.add_argument("--workspace")
    parser.add_argument("--project")
    parser.add_argument("--scheme")
    parser.add_argument("--configuration", default="Debug")
    parser.add_argument("--destination", default="generic/platform=iOS")
    parser.add_argument("--derived-data")
    parser.add_argument("--session")
    parser.add_argument("--beautify", choices=["auto", "always", "never"], default="auto")
    parser.add_argument("--xcbeautify-renderer", default="terminal", choices=["terminal", "github-actions", "teamcity", "azure-devops-pipelines"])
    parser.add_argument("--extra-xcodebuild-arg", action="append")


def add_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--session", default="latest")
    parser.add_argument("--device")
    parser.add_argument("--bundle-id")
    parser.add_argument("--process-name")
    parser.add_argument("--no-terminate-existing", action="store_true")
    parser.add_argument("--console", action="store_true")
    parser.add_argument("--launch-timeout", type=int, default=120)
    parser.add_argument("--log-duration", type=int)
    parser.add_argument("--app-argument", action="append")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    sub.add_parser("devices").set_defaults(func=cmd_devices)
    p = sub.add_parser("build")
    add_build_args(p)
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("install")
    p.add_argument("--session", default="latest")
    p.add_argument("--device")
    p.add_argument("--app-path")
    p.set_defaults(func=cmd_install)
    p = sub.add_parser("run")
    add_run_args(p)
    p.add_argument("--start-log", action="store_true", default=True)
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("build-run")
    add_build_args(p)
    p.add_argument("--device")
    p.add_argument("--app-path")
    p.add_argument("--bundle-id")
    p.add_argument("--process-name")
    p.add_argument("--no-terminate-existing", action="store_true")
    p.add_argument("--console", action="store_true")
    p.add_argument("--launch-timeout", type=int, default=120)
    p.add_argument("--log-duration", type=int)
    p.add_argument("--app-argument", action="append")
    p.set_defaults(func=cmd_build_run)
    p = sub.add_parser("log-stream")
    p.add_argument("--session", default="latest")
    p.add_argument("--device")
    p.add_argument("--bundle-id")
    p.add_argument("--process-name")
    p.add_argument("--log-duration", type=int)
    p.set_defaults(func=cmd_log_stream)
    p = sub.add_parser("stop-log")
    p.add_argument("--session", default="latest")
    p.add_argument("--delay", type=int)
    p.set_defaults(func=cmd_stop_log)
    p = sub.add_parser("logs")
    p.add_argument("--session", default="latest")
    p.add_argument("--file", choices=["build", "pretty", "run", "device", "all"], default="all")
    p.add_argument("--tail", type=int)
    p.add_argument("--grep")
    p.add_argument("--search")
    p.add_argument("--ignore-case", action="store_true")
    p.add_argument("--since")
    p.add_argument("--context", type=int, default=0)
    p.add_argument("--max-lines", type=int, default=300)
    p.add_argument("--line-numbers", action="store_true")
    p.set_defaults(func=cmd_logs)
    p = sub.add_parser("sessions")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_sessions)
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
