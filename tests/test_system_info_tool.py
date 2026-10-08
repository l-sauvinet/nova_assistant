import os

import pytest

from nova.tools.base import ToolError
from nova.tools.system_info import list_processes, system_overview


def test_overview_contains_date_ram_and_root_disk():
    overview = system_overview()
    assert "Date/time:" in overview and "RAM:" in overview and "  /:" in overview


def test_process_list_contains_current_process():
    assert str(os.getpid()) in list_processes(limit=10_000)


def test_process_list_rejects_unknown_sort():
    with pytest.raises(ToolError):
        list_processes(sort_by="name")
