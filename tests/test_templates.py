from pathlib import Path

from talos_panel.web import player_snapshot


def test_console_script_targets_command_input_not_csrf_input() -> None:
    template = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    assert "'.command-form input[name=\"command\"]'" in template


def test_player_snapshot_uses_latest_list_response() -> None:
    logs = """There are 0 of a max of 20 players online:
There are 2 of a max of 20 players online: Steve, Alex
"""
    assert player_snapshot(logs) == (2, 20, ["Steve", "Alex"])


def test_player_snapshot_is_unknown_before_list_response() -> None:
    assert player_snapshot("Done (1.23s)! For help, type \"help\"") == (None, None, [])


def test_delete_form_requires_typed_confirmation() -> None:
    template = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    assert "confirmation.value !== deleteForm.dataset.serverName" in template
    assert "window.confirm(" in template


def test_server_detail_uses_role_aware_client_side_tabs() -> None:
    template = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    assert 'data-tab="overview"' in template
    assert 'data-tab="console"' in template
    assert 'data-tab-panel="settings"' in template
    assert "selectTab(location.hash.slice(1) || 'overview', false)" in template


def test_dashboard_uses_runtime_state_and_completed_installation_is_hidden() -> None:
    index = Path("talos_panel/templates/index.html").read_text(encoding="utf-8")
    detail = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    installation = Path("talos_panel/templates/installation.html").read_text(encoding="utf-8")
    assert 'card.runtime_state == "running"' in index
    assert 'display_state = "offline"' in index
    assert 'server.installation_state.value != "completed"' in detail
    assert 'job.state.value != "completed"' in installation


def test_file_manager_is_a_server_tab_and_uses_safe_dom_rendering() -> None:
    template = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    assert 'data-tab="files"' in template
    assert 'data-tab-panel="files"' in template
    assert "name.textContent" in template
    assert "encodeURIComponent(entry.path)" in template


def test_notifications_use_toasts_and_editor_content_is_not_reset_after_save() -> None:
    base = Path("talos_panel/templates/base.html").read_text(encoding="utf-8")
    detail = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    assert 'id="toast-region"' in base
    assert "window.talosToast" in base
    assert "const isEditor = form.id === 'text-editor'" in detail
    assert "form.querySelector('.editor-state').textContent = ui.saved" in detail


def test_installation_updates_without_reload_and_guards_start_action() -> None:
    template = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    assert "async function pollInstallation()" in template
    assert "/api/v1/servers/{{ server.id }}/installation" in template
    assert "setTimeout(pollInstallation, 1000)" in template
    assert "installationComplete = true" in template
    assert "data.state === 'running' || !installationComplete" in template


def test_opening_console_scrolls_to_latest_output() -> None:
    template = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    assert "if (selected.dataset.tab === 'console')" in template
    assert "output.scrollTop = output.scrollHeight" in template


def test_server_detail_uses_framed_sidebar_workspace() -> None:
    template = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    assert 'class="server-shell"' in template
    assert 'class="server-sidebar"' in template
    assert 'class="server-workspace"' in template


def test_fonts_are_self_hosted_for_content_security_policy() -> None:
    template = Path("talos_panel/templates/base.html").read_text(encoding="utf-8")
    fonts = Path("talos_panel/static/fonts.css").read_text(encoding="utf-8")
    assert 'href="/static/fonts.css"' in template
    assert "fonts.googleapis.com" not in template
    assert 'url("/static/fonts/' in fonts


def test_server_cards_do_not_show_redundant_open_label() -> None:
    template = Path("talos_panel/templates/index.html").read_text(encoding="utf-8")
    assert "Open server" not in template


def test_server_workspace_uses_full_screen_layout() -> None:
    stylesheet = Path("talos_panel/static/async.css").read_text(encoding="utf-8")
    assert "main:has(.server-shell)" in stylesheet
    assert "max-width: none" in stylesheet
    assert "min-height: 100vh" in stylesheet
    assert "calc(100vh - 72px)" not in stylesheet
    assert "grid-template-columns: 224px minmax(0, 1fr)" in stylesheet


def test_dashboard_uses_sidebar_and_server_rows() -> None:
    base = Path("talos_panel/templates/base.html").read_text(encoding="utf-8")
    index = Path("talos_panel/templates/index.html").read_text(encoding="utf-8")
    assert 'class="app-sidebar"' in base
    assert "<header>" not in base
    assert 'class="server-list"' in index
    assert 'class="server-row"' in index
    assert 'class="card server-card"' not in index


def test_language_switch_and_translated_javascript_are_present() -> None:
    base = Path("talos_panel/templates/base.html").read_text(encoding="utf-8")
    detail = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    assert 'action="/language/en"' in base
    assert 'action="/language/pl"' in base
    assert '<html lang="{{ lang }}">' in base
    assert "const ui = {" in detail


def test_sidebar_utilities_are_anchored_in_shared_footer() -> None:
    base = Path("talos_panel/templates/base.html").read_text(encoding="utf-8")
    stylesheet = Path("talos_panel/static/async.css").read_text(encoding="utf-8")
    footer = base.split('class="app-sidebar-foot"', 1)[1]
    assert 'class="language-switch"' in footer
    assert 'class="sidebar-foot-link"' in footer
    assert "margin-top: auto" in stylesheet
    assert ".server-tabs button:hover" in stylesheet
    assert "font-weight: 500" in stylesheet
