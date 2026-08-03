from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from talos_panel.web import minecraft_is_ready, player_snapshot


def test_console_script_targets_command_input_not_csrf_input() -> None:
    template = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    assert "'.command-form input[name=\"command\"]'" in template


def test_console_uses_the_available_workspace_height() -> None:
    stylesheet = Path("talos_panel/static/async.css").read_text(encoding="utf-8")
    assert ".server-workspace:has(#tab-console:not(.hidden))" in stylesheet
    assert "#tab-console:not(.hidden)" in stylesheet
    assert ".console-card {" in stylesheet


def test_player_snapshot_uses_latest_list_response() -> None:
    logs = """There are 0 of a max of 20 players online:
There are 2 of a max of 20 players online: Steve, Alex
"""
    assert player_snapshot(logs) == (2, 20, ["Steve", "Alex"])


def test_player_snapshot_is_unknown_before_list_response() -> None:
    assert player_snapshot("Done (1.23s)! For help, type \"help\"") == (None, None, [])


def test_minecraft_ready_requires_a_running_container() -> None:
    logs = 'Done (1.23s)! For help, type "help"'
    assert minecraft_is_ready("running", logs) is True
    assert minecraft_is_ready("exited", logs) is False
    assert minecraft_is_ready("running", "Starting Minecraft server") is False


def test_delete_form_requires_typed_confirmation() -> None:
    template = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    assert "confirmation.value !== deleteForm.dataset.serverName" in template
    assert "window.confirm(" not in template
    assert "window.prompt(" not in template
    assert 'id="action-confirm-dialog"' in template
    assert 'id="server-delete-dialog"' in template
    assert "Delete this server from Talos Panel?" not in template
    assert "deleteDialog.showModal()" in template


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


def test_dashboard_server_rows_are_not_wrapped_in_a_card() -> None:
    stylesheet = Path("talos_panel/static/async.css").read_text(encoding="utf-8")
    dashboard_styles = stylesheet[stylesheet.index(".dashboard-title {") :]
    server_list_rule = dashboard_styles[
        dashboard_styles.index(".server-list {") : dashboard_styles.index(".server-list-body {")
    ]
    assert "border: 0" in server_list_rule
    assert "background: transparent" in server_list_rule
    assert ".dashboard-title" in stylesheet


def test_file_manager_is_a_server_tab_and_uses_safe_dom_rendering() -> None:
    template = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    assert 'data-tab="files"' in template
    assert 'data-tab-panel="files"' in template
    assert "name.textContent" in template
    assert "encodeURIComponent(entry.path)" in template
    assert "file-delete-dialog" in template
    assert "Move ${path} to the Talos trash?" not in template
    assert "Stop the server before uploading, editing, creating, deleting" not in template
    assert "renderConsoleOutput" in template
    assert 'class="file-picker"' in template


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


def test_console_only_follows_logs_when_reader_is_near_the_bottom() -> None:
    template = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    assert "function consoleIsNearBottom()" in template
    assert "const followConsole = consoleIsNearBottom()" in template
    assert "followConsole ? output.scrollHeight : previousConsoleScroll" in template


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
    assert "grid-template-columns: var(--sidebar-width) minmax(0, 1fr)" in stylesheet


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
    detail = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    utilities = Path("talos_panel/templates/_sidebar_utilities.html").read_text(encoding="utf-8")
    stylesheet = Path("talos_panel/static/async.css").read_text(encoding="utf-8")
    assert '{% include "_sidebar_utilities.html" %}' in base
    assert '{% include "_sidebar_utilities.html" %}' in detail
    assert 'class="language-switch"' in utilities
    assert 'class="sidebar-identity"' in utilities
    assert "request.state.user.role.value" in utilities
    assert "margin-top: auto" in stylesheet
    assert ".server-tabs button:hover" in stylesheet
    assert "font-weight: 500" in stylesheet


def test_sidebar_navigation_and_server_identity_are_consistent() -> None:
    base = Path("talos_panel/templates/base.html").read_text(encoding="utf-8")
    detail = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    utilities = Path("talos_panel/templates/_sidebar_utilities.html").read_text(encoding="utf-8")
    stylesheet = Path("talos_panel/static/async.css").read_text(encoding="utf-8")
    assert base.index('href="/admin/users"') < base.index('{% include "_sidebar_utilities.html" %}')
    assert 'href="/admin/security"' in base
    assert 'href="/admin/audit"' in base
    assert utilities.index('class="sidebar-identity"') < utilities.index('class="language-switch"')
    assert 'class="app-brand" href="/"' in detail
    assert 'class="server-heading-identity"' in detail
    assert 'id="sidebar-runtime"' not in detail
    assert "sidebarRuntime" not in detail
    assert "brand-cube" not in base
    assert "brand-cube" not in detail
    assert "Minecraft control" not in detail
    assert 'class="server-home-link" href="/"' in detail
    assert "All servers" not in detail
    assert "border-bottom: 1px solid var(--line)" in stylesheet
    assert ".server-home-link:hover" in stylesheet
    assert 'class="server-navigation"' in detail
    assert ".app-nav a,\n.server-home-link,\n.server-tabs button" in stylesheet
    assert "padding: 9px 10px" in stylesheet


def test_server_list_spacing_and_motion_use_design_tokens() -> None:
    stylesheet = Path("talos_panel/static/async.css").read_text(encoding="utf-8")
    assert "--sidebar-width: 224px" in stylesheet
    assert stylesheet.count(
        "padding: var(--sidebar-padding-top) var(--sidebar-padding-x) "
        "var(--sidebar-padding-bottom)"
    ) == 2
    assert "--space-6: 24px" in stylesheet
    assert "min-height: 80px" in stylesheet
    assert "font-size: 10.5px" in stylesheet
    assert "@keyframes workspace-enter" in stylesheet
    assert "prefers-reduced-motion: reduce" in stylesheet


def test_access_views_explain_account_state_and_show_server_roles() -> None:
    users = Path("talos_panel/templates/users.html").read_text(encoding="utf-8")
    detail = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    assert "Active means that the account is allowed to log in." in users
    assert "access_by_user.get(user.id)" in users
    assert "Full access to every server (global administrator)." in users
    assert "member_rows" in detail
    assert "Remove access" in detail
    assert 'class="access-grid"' in detail


def test_file_manager_downloads_directories_and_server_list_scrolls() -> None:
    detail = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    index = Path("talos_panel/templates/index.html").read_text(encoding="utf-8")
    stylesheet = Path("talos_panel/static/async.css").read_text(encoding="utf-8")
    assert "const download = document.createElement('a');" in detail
    assert 'class="server-list-body"' in index
    assert ".server-list-body" in stylesheet
    assert "overflow-y: auto" in stylesheet
    assert "justify-content: center" in stylesheet


def test_dashboard_is_wider_and_shows_players_and_live_uptime() -> None:
    index = Path("talos_panel/templates/index.html").read_text(encoding="utf-8")
    stylesheet = Path("talos_panel/static/async.css").read_text(encoding="utf-8")
    assert 'class="dashboard-page"' in index
    assert 'class="server-player-count"' in index
    assert 'class="server-uptime"' in index
    assert "data-started-at" in index
    assert "updateUptimes" in index
    assert "main:has(.dashboard-page)" in stylesheet
    assert "max-width: 1500px" in stylesheet


def test_dashboard_loads_runtime_summaries_after_initial_render() -> None:
    index = Path("talos_panel/templates/index.html").read_text(encoding="utf-8")
    web = Path("talos_panel/web.py").read_text(encoding="utf-8")
    assert 'data-summary-url="/servers/{{ server.id }}/summary"' in index
    assert "refreshSummaries()" in index
    assert "window.setInterval(refreshSummaries, 10000)" in index
    assert 'runtime_state": "loading"' in web
    assert 'send_command(server, "list")' not in web
    assert "query_minecraft_status(" in web


def test_dashboard_and_login_use_viewport_bounded_layouts() -> None:
    stylesheet = Path("talos_panel/static/async.css").read_text(encoding="utf-8")
    assert "body:has(.public-main)" in stylesheet
    assert "height: 100dvh" in stylesheet
    assert ".public-main .auth-card" in stylesheet
    assert ".app-frame:has(.dashboard-page)" in stylesheet
    assert ".dashboard-page .server-list-body" in stylesheet


def test_ui_polish_uses_balanced_dashboard_branding_and_static_cards() -> None:
    detail = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    stylesheet = Path("talos_panel/static/async.css").read_text(encoding="utf-8")
    assert "Commands are sent directly to Minecraft stdin" not in detail
    assert "Symbolic links and protected Talos files" not in detail
    assert "font-size: 11px" in stylesheet
    assert "letter-spacing: .04em" in stylesheet
    assert stylesheet.count("padding-top: var(--space-8)") >= 1
    assert stylesheet.count("padding-bottom: var(--space-8)") >= 1
    assert ".server-workspace .card:hover" in stylesheet


def test_file_manager_uses_general_file_and_folder_uploads() -> None:
    detail = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    stylesheet = Path("talos_panel/static/async.css").read_text(encoding="utf-8")
    file_service = Path("talos_panel/file_service.py").read_text(encoding="utf-8")
    web = Path("talos_panel/web.py").read_text(encoding="utf-8")
    assert 'id="folder-upload-form"' in detail
    assert "webkitdirectory multiple" in detail
    assert "file.webkitRelativePath || file.name" in detail
    assert 'id="plugin-upload-form"' not in detail
    assert "/plugins/upload" not in detail
    assert "Use the Paper plugin upload" not in file_service
    assert 'id="upload-progress"' in detail
    assert 'id="file-drop-overlay"' in detail
    assert "Drag and drop files or folders onto the file list" in detail
    assert 'id="text-editor-dialog"' in detail
    assert "dialog.showModal()" in detail
    assert ".text-editor-dialog" in stylesheet
    assert "request.upload.addEventListener('progress'" in detail
    assert "filesFromEntry" in detail
    assert "openOrganizeDialog('rename'" in detail
    assert "openOrganizeDialog('move'" in detail
    assert "openOrganizeDialog('copy'" in detail
    assert "/files/organize" in web
    assert "/files/extract" in web
    assert "extract_zip" in file_service


def test_server_heading_avoids_duplicate_metadata_and_version_includes_software() -> None:
    detail = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    assert "{{ server.game_version }} · localhost:{{ server.host_port }}" not in detail
    assert "{{ server.server_type.value|title }} {{ server.installed_version }}" in detail
    assert "const serverSoftware" in detail
    assert "`${serverSoftware} ${data.installed_version}`" in detail


def test_console_header_and_server_details_avoid_redundant_labels_and_rules() -> None:
    detail = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    stylesheet = Path("talos_panel/static/async.css").read_text(encoding="utf-8")
    assert 'id="console-status"' not in detail
    assert "Live output" not in detail
    assert "Minecraft ready" not in detail
    assert 't("Console ready")' in detail
    assert ".details div:last-child" in stylesheet


def test_backups_have_a_dedicated_safe_management_tab() -> None:
    detail = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    stylesheet = Path("talos_panel/static/async.css").read_text(encoding="utf-8")
    assert 'data-tab="backups"' in detail
    assert 'data-tab-panel="backups"' in detail
    assert 'action="/servers/{{ server.id }}/backups"' in detail
    assert "backup-restore-form" in detail
    assert "backup-delete-form" in detail
    assert "backup-requires-stopped" in detail
    assert ".backup-list" in stylesheet
    assert ".server-workspace:has(#tab-backups:not(.hidden))" in stylesheet
    assert "#tab-backups:not(.hidden)" in stylesheet
    backup_styles = stylesheet.split(".backup-list {", 1)[1].split("}", 1)[0]
    assert "overflow-y: auto" in backup_styles
    assert "overscroll-behavior: contain" in backup_styles


def test_players_have_profiles_and_async_administration_actions() -> None:
    detail = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    stylesheet = Path("talos_panel/static/async.css").read_text(encoding="utf-8")
    web = Path("talos_panel/web.py").read_text(encoding="utf-8")
    assert 'data-tab="players"' in detail
    assert 'data-tab-panel="players"' in detail
    assert "loadPlayerProfiles" in detail
    assert "playerTableBody.addEventListener('click'" in detail
    assert "/players/${encodeURIComponent(button.dataset.player)}/action" in detail
    assert ".player-table" in stylesheet
    assert "PLAYER_ACTION_COMMANDS" in web
    assert 'f"player.{action}"' in web
    assert '/players/${encodeURIComponent(player.uuid)}/avatar' in detail
    assert ".player-avatar img" in stylesheet


def test_operational_tabs_cover_backups_updates_and_monitoring() -> None:
    detail = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    base = Path("talos_panel/templates/base.html").read_text(encoding="utf-8")
    stylesheet = Path("talos_panel/static/async.css").read_text(encoding="utf-8")
    web = Path("talos_panel/web.py").read_text(encoding="utf-8")
    operations = Path("talos_panel/operations_service.py").read_text(encoding="utf-8")
    assert 'data-tab="updates"' in detail
    assert 'data-tab="monitoring"' in detail
    assert 'class="backup-policy"' in detail
    assert "Backup and update" in detail
    assert "metrics-chart" in detail
    assert 'id="monitoring-cpu"' in detail
    assert 'id="monitoring-memory"' in detail
    assert 'class="runtime-history"' in detail
    assert 'class="backup-create-form"' in detail
    assert "submitLongOperation" in detail
    assert "socketRenderTimer" in detail
    assert "window.talosOperation" in base
    assert ".operation-spinner" in stylesheet
    assert "overflow-y: auto" in stylesheet
    assert "create_backup" in web
    assert "restore_backup" in web
    assert "server.auto_restart" in operations
    assert "save-all flush" in operations
    assert ".server-workspace:has(#tab-updates:not(.hidden))" in stylesheet
    assert "#tab-updates:not(.hidden)" in stylesheet
    update_styles = stylesheet.split(".update-history {", 1)[1].split("}", 1)[0]
    assert "overflow-y: auto" in update_styles
    assert "flex: 1" in update_styles


def test_small_ui_consistency_details() -> None:
    detail = Path("talos_panel/templates/server_detail.html").read_text(encoding="utf-8")
    create = Path("talos_panel/templates/new_server.html").read_text(encoding="utf-8")
    assert 'class="copy mini-button"' in detail
    assert "Read / write" not in detail
    assert '<span class="status">{{ t("Owner") }}</span>' not in detail
    assert 'class="check eula-check"' in create
    assert "</a>.</span>" not in create


def test_account_has_two_factor_sessions_and_security_review() -> None:
    account = Path("talos_panel/templates/account.html").read_text(encoding="utf-8")
    login = Path("talos_panel/templates/login.html").read_text(encoding="utf-8")
    security = Path("talos_panel/templates/security_review.html").read_text(encoding="utf-8")
    audit = Path("talos_panel/templates/audit_logs.html").read_text(encoding="utf-8")
    assert 'action="/account/2fa"' in account
    assert "totp_code" in login
    assert "Active sessions" in account
    assert "/account/sessions/{{ session.id }}/revoke" in account
    assert "Security review" in security
    assert "audit_action" in audit


def test_all_jinja_templates_compile() -> None:
    environment = Environment(loader=FileSystemLoader("talos_panel/templates"))
    for template_name in environment.list_templates():
        environment.get_template(template_name)


def test_server_creation_uses_full_width_sections_and_jvm_options() -> None:
    template = Path("talos_panel/templates/new_server.html").read_text(encoding="utf-8")
    stylesheet = Path("talos_panel/static/async.css").read_text(encoding="utf-8")
    assert 'class="server-create-page"' in template
    assert 'name="use_aikar_flags"' in template
    assert 'name="custom_jvm_flags"' in template
    assert ".server-create-form:hover" in stylesheet
    assert "font-weight: 400" in stylesheet


def test_stop_intent_is_persisted_before_stopping_container() -> None:
    web = Path("talos_panel/web.py").read_text(encoding="utf-8")
    stop_handler = web[web.index("async def stop_server_ui") : web.index("async def restart_server_ui")]
    assert stop_handler.index("server.desired_state = DesiredState.STOPPED") < stop_handler.index(
        "await runtime.stop(server)"
    )
