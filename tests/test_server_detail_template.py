from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES = Path(__file__).parents[1] / "talos_panel" / "templates"


def test_server_detail_guards_owner_only_monitoring_elements() -> None:
    source = (TEMPLATES / "server_detail.html").read_text(encoding="utf-8")

    assert "if (monitoringCpu) monitoringCpu.textContent" in source
    assert "if (monitoringMemory) monitoringMemory.textContent" in source
    assert "if (monitoringPlayers) monitoringPlayers.textContent" in source


def test_all_templates_compile_after_server_detail_split() -> None:
    environment = Environment(loader=FileSystemLoader(TEMPLATES))

    for name in environment.list_templates():
        environment.get_template(name)
