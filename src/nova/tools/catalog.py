from nova.config import Settings
from nova.tools.base import Tool
from nova.tools.creative import CreativeStudio, PollinationsImageGenerator, build_creative_tools
from nova.tools.disk_usage import DiskUsageAnalyzer, build_disk_usage_tools
from nova.tools.documents import DocumentStudio, build_document_tools
from nova.tools.file_access import FileAccessGuard
from nova.tools.files import FileManager, build_file_tools
from nova.tools.shell import ShellRunner, build_shell_tools
from nova.tools.system_info import build_system_info_tools
from nova.tools.web import WebBrowser, build_web_tools, duckduckgo_search


def build_default_tools(settings: Settings, access: FileAccessGuard) -> list[Tool]:
    tools = build_file_tools(FileManager(access, max_read_bytes=settings.max_read_bytes))
    tools += build_disk_usage_tools(DiskUsageAnalyzer(access, settings.disk_scan_timeout_seconds))
    tools += build_system_info_tools()
    tools += build_web_tools(WebBrowser(duckduckgo_search(settings.web_region)))
    tools += build_document_tools(DocumentStudio(access))
    tools += build_creative_tools(CreativeStudio(access, PollinationsImageGenerator(settings.image_model)))
    if settings.shell_enabled:
        tools += build_shell_tools(ShellRunner(access, settings.shell_timeout_seconds))
    return tools
