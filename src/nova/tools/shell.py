import subprocess
from collections.abc import Callable
from pathlib import Path

from nova.device.machine import Shell, default_shell
from nova.security.injection import risky_command
from nova.tools.base import Tool, ToolError, object_schema
from nova.tools.file_access import FileAccessGuard

MAX_OUTPUT_CHARS = 20_000

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]

# Windows PowerShell 5.1 writes in the console's legacy code page when piped: force UTF-8 so accents survive.
POWERSHELL_UTF8 = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8; "


class ShellRunner:
    """Runs shell commands (bash, or PowerShell on Windows). Every command is shown to the user and must be approved."""

    def __init__(
        self,
        access: FileAccessGuard,
        timeout_seconds: int = 120,
        run_command: CommandRunner | None = None,
        shell: Shell | None = None,
    ) -> None:
        self.access = access
        self.shell = shell or default_shell()
        self.timeout_seconds = timeout_seconds
        self.run_command = run_command or subprocess.run

    def run(self, command: str, explanation: str, working_directory: str = ".") -> str:
        directory = self._working_directory(working_directory)
        try:
            completed = self.run_command(
                self.command_line(command),
                cwd=directory,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout_seconds,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as error:
            raise ToolError(f"Command timed out after {self.timeout_seconds}s: {command}") from error
        return format_command_output(completed.returncode, completed.stdout, completed.stderr)

    def command_line(self, command: str) -> list[str]:
        if self.shell == "powershell":
            return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", POWERSHELL_UTF8 + command]
        return ["bash", "-c", command]

    def confirmation(self, command: str, explanation: str, working_directory: str = ".") -> str:
        """First line: plain-language purpose for the user; the rest: technical detail (shown folded)."""
        directory = self._working_directory(working_directory)
        return f"{explanation.strip().rstrip('.')} ?\nCommande exécutée dans {directory} :\n$ {command}"

    def danger(self, command: str, explanation: str, working_directory: str = ".") -> str | None:
        if not risky_command(command):
            return None
        return (
            "⚠️ Cette commande ressemble à celles des attaques : elle peut télécharger et lancer un programme, "
            "désactiver une protection ou effacer beaucoup de fichiers. Lis-la avant d'autoriser."
        )

    def _working_directory(self, working_directory: str) -> Path:
        directory = self.access.resolve(working_directory)
        if not directory.is_dir():
            raise ToolError(f"Working directory not found: {directory}")
        return directory


def format_command_output(returncode: int, stdout: str, stderr: str) -> str:
    sections = [f"Exit code: {returncode}"]
    if stdout.strip():
        sections.append("stdout:\n" + truncate(stdout))
    if stderr.strip():
        sections.append("stderr:\n" + truncate(stderr))
    if len(sections) == 1:
        sections.append("(no output)")
    return "\n".join(sections)


def truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n... output truncated ({len(text)} characters in total)."


def build_shell_tools(runner: ShellRunner) -> list[Tool]:
    shell = "Windows PowerShell 5.1" if runner.shell == "powershell" else "bash"
    return [
        Tool(
            name="run_command",
            description=(
                f"Run a {shell} command on the user's computer and return its exit code and output. "
                "The user approves every command before it runs. Non-interactive only: no command waiting for "
                "keyboard input. Prefer the dedicated tools (files, folder sizes, system info) when they fit."
            ),
            parameters=object_schema(
                {
                    "command": {"type": "string", "description": f"The {shell} command line."},
                    "explanation": {
                        "type": "string",
                        "description": (
                            "What the command does, in one short plain French sentence for a non-technical user, "
                            "starting with a verb (e.g. 'Créer le PDF du cours de droit pénal dans Documents'). "
                            "Never mention code, scripts or command names."
                        ),
                    },
                    "working_directory": {
                        "type": "string",
                        "description": "Folder to run in. Defaults to NOVA's workspace.",
                    },
                },
                required=["command", "explanation"],
            ),
            run=runner.run,
            confirmation_prompt=runner.confirmation,
            effect="changes",
            danger=runner.danger,
        )
    ]
