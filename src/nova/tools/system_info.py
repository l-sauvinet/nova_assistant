import platform
import shutil
import time
from datetime import datetime
from pathlib import Path

import psutil

from nova.tools.base import Tool, ToolError, object_schema
from nova.tools.disk_usage import human_size


def system_overview() -> str:
    now = datetime.now().astimezone()
    memory = psutil.virtual_memory()
    boot = datetime.fromtimestamp(psutil.boot_time()).astimezone()
    lines = [
        f"Date/time: {now:%A %d %B %Y, %H:%M:%S} ({now.tzname()})",
        f"Machine: {platform.node()} — {platform.system()} {platform.release()} ({platform.machine()})",
        f"Up since: {boot:%Y-%m-%d %H:%M}",
        f"CPU: {psutil.cpu_count(logical=True)} logical cores, usage {psutil.cpu_percent(interval=0.5):.0f}%",
        f"RAM: {human_size(memory.used)} used / {human_size(memory.total)} ({memory.percent:.0f}%)",
        "Disks:",
    ]
    for mount in disk_mount_points():
        try:
            usage = shutil.disk_usage(mount)
        except OSError:
            continue
        lines.append(
            f"  {mount}: {human_size(usage.used)} used / {human_size(usage.total)}, {human_size(usage.free)} free"
        )
    return "\n".join(lines)


def disk_mount_points() -> list[str]:
    mounts = ["/"]
    windows_drives = Path("/mnt")
    if windows_drives.is_dir():
        mounts += sorted(str(drive) for drive in windows_drives.iterdir() if len(drive.name) == 1 and drive.is_dir())
    return mounts


def list_processes(sort_by: str = "memory", limit: int = 15) -> str:
    if sort_by not in {"memory", "cpu"}:
        raise ToolError("sort_by must be 'memory' or 'cpu'.")
    processes = list(psutil.process_iter(["pid", "name", "username", "memory_info"]))
    for process in processes:
        try:
            process.cpu_percent(None)
        except psutil.Error:
            pass
    time.sleep(0.5)
    rows = []
    for process in processes:
        try:
            cpu = process.cpu_percent(None)
            memory = process.info["memory_info"].rss if process.info["memory_info"] else 0
            rows.append((process.info["pid"], process.info["name"] or "?", process.info["username"] or "?", cpu, memory))
        except psutil.Error:
            continue
    rows.sort(key=lambda row: row[3] if sort_by == "cpu" else row[4], reverse=True)
    lines = [f"{'PID':>7}  {'CPU%':>5}  {'RAM':>9}  {'USER':<10} NAME"]
    for pid, name, user, cpu, memory in rows[: max(1, limit)]:
        lines.append(f"{pid:>7}  {cpu:>5.1f}  {human_size(memory):>9}  {user[:10]:<10} {name}")
    return "\n".join(lines)


def build_system_info_tools() -> list[Tool]:
    return [
        Tool(
            name="system_info",
            description="Current date and time, machine, uptime, CPU and RAM usage, disk space of Linux and Windows drives.",
            parameters=object_schema({}, required=[]),
            run=system_overview,
        ),
        Tool(
            name="list_processes",
            description="List running processes (Linux side) with their CPU and RAM usage.",
            parameters=object_schema(
                {
                    "sort_by": {"type": "string", "enum": ["memory", "cpu"], "description": "Default memory."},
                    "limit": {"type": "integer", "description": "Default 15."},
                },
                required=[],
            ),
            run=list_processes,
        ),
    ]
