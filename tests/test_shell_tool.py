import subprocess
from pathlib import Path

import pytest

from nova.core.messages import ToolCall
from nova.tools.base import ToolError
from nova.tools.file_access import FileAccessGuard
from nova.tools.registry import CANCELLED_BY_USER, ToolRegistry
from nova.tools.shell import MAX_OUTPUT_CHARS, ShellRunner, build_shell_tools, format_command_output
from fakes import ScriptedConfirmer


class FakeCommandRunner:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0, raise_timeout: bool = False) -> None:
        self.stdout, self.stderr, self.returncode, self.raise_timeout = stdout, stderr, returncode, raise_timeout
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, command, cwd, **kwargs):
        self.calls.append((command, cwd))
        if self.raise_timeout:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, self.returncode, self.stdout, self.stderr)


def make_registry(tmp_path: Path, confirm: bool, runner: FakeCommandRunner, shell_name: str = "bash"):
    confirmer = ScriptedConfirmer(confirm)
    shell = ShellRunner(FileAccessGuard([tmp_path], confirmer), timeout_seconds=5, run_command=runner, shell=shell_name)
    return ToolRegistry(build_shell_tools(shell), confirmer), confirmer


def run_command(registry: ToolRegistry, **arguments):
    return registry.execute(ToolCall(id="1", name="run_command", arguments=arguments))


def test_windows_commands_run_in_powershell_with_utf8_output(tmp_path: Path):
    runner = FakeCommandRunner(stdout="café\n")
    registry, _ = make_registry(tmp_path, confirm=True, runner=runner, shell_name="powershell")
    run_command(registry, command="Get-ChildItem", explanation="Lister les fichiers")
    command_line = runner.calls[0][0]
    assert command_line[:4] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
    assert command_line[4].startswith("[Console]::OutputEncoding") and command_line[4].endswith("Get-ChildItem")
    assert "Windows PowerShell" in registry.specs()[0].description


def test_command_runs_after_approval_in_workspace(tmp_path: Path):
    runner = FakeCommandRunner(stdout="4.0G\t/home\n")
    registry, confirmer = make_registry(tmp_path, confirm=True, runner=runner)
    result = run_command(registry, command="du -sh /home", explanation="Mesurer la taille du dossier home")
    assert runner.calls == [(["bash", "-c", "du -sh /home"], tmp_path.resolve())]
    assert "Exit code: 0" in result.content and "4.0G" in result.content
    assert confirmer.questions[0].splitlines()[0] == "Mesurer la taille du dossier home ?"
    assert "$ du -sh /home" in confirmer.questions[0]


def test_command_is_not_run_when_refused(tmp_path: Path):
    runner = FakeCommandRunner()
    registry, _ = make_registry(tmp_path, confirm=False, runner=runner)
    assert run_command(registry, command="rm -rf ~/old", explanation="Supprimer le dossier old").content == CANCELLED_BY_USER
    assert runner.calls == []


def test_custom_working_directory(tmp_path: Path):
    (tmp_path / "project").mkdir()
    runner = FakeCommandRunner()
    registry, _ = make_registry(tmp_path, confirm=True, runner=runner)
    run_command(registry, command="git status", explanation="Voir l'état du projet", working_directory="project")
    assert runner.calls[0][1] == tmp_path.resolve() / "project"


def test_missing_working_directory_fails_before_asking(tmp_path: Path):
    runner = FakeCommandRunner()
    registry, confirmer = make_registry(tmp_path, confirm=True, runner=runner)
    result = run_command(registry, command="ls", explanation="Lister", working_directory="nope")
    assert result.is_error and confirmer.questions == [] and runner.calls == []


def test_timeout_is_reported(tmp_path: Path):
    registry, _ = make_registry(tmp_path, confirm=True, runner=FakeCommandRunner(raise_timeout=True))
    result = run_command(registry, command="sleep 100", explanation="Attendre")
    assert result.is_error and "timed out" in result.content


def test_failed_command_reports_exit_code_and_stderr():
    output = format_command_output(2, "", "ls: cannot access 'x'")
    assert "Exit code: 2" in output and "stderr:\nls: cannot access" in output


def test_empty_output_is_explicit():
    assert "(no output)" in format_command_output(0, "", "")


def test_long_output_is_truncated():
    output = format_command_output(0, "x" * (MAX_OUTPUT_CHARS + 10), "")
    assert "output truncated" in output


def test_timeout_error_type(tmp_path: Path):
    shell = ShellRunner(FileAccessGuard([tmp_path], ScriptedConfirmer()), run_command=FakeCommandRunner(raise_timeout=True))
    with pytest.raises(ToolError):
        shell.run("sleep 100", "Attendre")


def test_explanation_is_required(tmp_path: Path):
    runner = FakeCommandRunner()
    registry, confirmer = make_registry(tmp_path, confirm=True, runner=runner)
    result = run_command(registry, command="ls")
    assert result.is_error and "explanation" in result.content and runner.calls == []


def test_multiline_command_keeps_its_indentation_in_the_confirmation(tmp_path: Path):
    runner = FakeCommandRunner()
    registry, confirmer = make_registry(tmp_path, confirm=True, runner=runner)
    script = "python3 << 'EOF'\nfor i in range(2):\n    print(i)\nEOF"
    run_command(registry, command=script, explanation="Afficher deux nombres")
    assert "\n    print(i)\n" in confirmer.questions[0]
