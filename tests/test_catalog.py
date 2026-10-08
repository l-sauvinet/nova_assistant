from pathlib import Path

from nova.config import Settings
from nova.tools.catalog import build_default_tools
from nova.tools.file_access import FileAccessGuard
from fakes import ScriptedConfirmer


def tool_names(tmp_path: Path, **overrides) -> set[str]:
    settings = Settings(_env_file=None, trusted_dirs=[tmp_path], **overrides)
    return {tool.name for tool in build_default_tools(settings, FileAccessGuard([tmp_path], ScriptedConfirmer()))}


def test_all_tool_families_are_available(tmp_path: Path):
    assert tool_names(tmp_path) >= {
        "read_file", "folder_sizes", "system_info", "list_processes", "web_search", "fetch_page", "run_command",
        "generate_image", "create_artifact", "create_document", "share_file",
    }


def test_shell_can_be_disabled(tmp_path: Path):
    assert "run_command" not in tool_names(tmp_path, shell_enabled=False)
