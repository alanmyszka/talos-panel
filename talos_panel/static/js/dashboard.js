const dashboard = document.querySelector('.dashboard-page');
const labels = {
  running: dashboard.dataset.labelRunning,
  starting: dashboard.dataset.labelStarting,
  offline: dashboard.dataset.labelOffline,
  installing: dashboard.dataset.labelInstalling,
  failed: dashboard.dataset.labelFailed,
  error: dashboard.dataset.labelError,
};

if (dashboard.dataset.message) window.talosToast(dashboard.dataset.message);

const formatUptime = seconds => {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
};

const updateUptimes = () => {
  document.querySelectorAll('.server-uptime[data-started-at]').forEach(item => {
    const startedAt = Date.parse(item.dataset.startedAt);
    if (!Number.isNaN(startedAt)) {
      item.textContent = formatUptime(Math.max(0, (Date.now() - startedAt) / 1000));
    }
  });
};

const updateSummary = (row, data) => {
  const status = row.querySelector('.server-runtime-status');
  let state;
  if (data.installation_state === 'failed') state = 'failed';
  else if (data.installation_state !== 'completed') state = 'installing';
  else if (data.runtime_state === 'running') state = data.minecraft_ready ? 'running' : 'starting';
  else if (['not_created', 'created', 'exited', 'dead'].includes(data.runtime_state)) state = 'offline';
  else state = 'error';
  status.textContent = labels[state];
  status.className = `status server-runtime-status state-${state}`;
  row.querySelector('.server-player-count').textContent = data.minecraft_ready
    ? `${data.players_online} / ${data.players_max}` : '—';
  if (data.installed_version) {
    const version = row.querySelector('.server-version');
    version.textContent = `${version.textContent.split(' ')[0]} ${data.installed_version}`;
  }
  const uptime = row.querySelector('.server-uptime');
  if (data.started_at) uptime.dataset.startedAt = data.started_at;
  else {
    delete uptime.dataset.startedAt;
    uptime.textContent = '—';
  }
};

let refreshInProgress = false;
const refreshSummaries = async () => {
  if (document.hidden || refreshInProgress) return;
  refreshInProgress = true;
  try {
    const response = await fetch('/servers/summaries', {
      headers: {'Accept': 'application/json'},
    });
    if (!response.ok) throw new Error('summaries unavailable');
    const payload = await response.json();
    const summaries = new Map(payload.servers.map(summary => [summary.server_id, summary]));
    document.querySelectorAll('.server-row[data-server-id]').forEach(row => {
      const summary = summaries.get(row.dataset.serverId);
      if (summary) updateSummary(row, summary);
    });
    updateUptimes();
  } catch (error) {
    document.querySelectorAll('.server-row[data-server-id] .server-runtime-status')
      .forEach(status => {
        status.textContent = labels.error;
        status.className = 'status server-runtime-status state-error';
      });
  } finally {
    refreshInProgress = false;
  }
};

updateUptimes();
refreshSummaries();
window.setInterval(updateUptimes, 30000);
window.setInterval(refreshSummaries, 15000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) refreshSummaries();
});
