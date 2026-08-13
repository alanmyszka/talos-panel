const typeSelect = document.querySelector('#server-type');
const versionSelect = document.querySelector('#version');

async function loadVersions() {
  const loadingOption = document.createElement('option');
  loadingOption.textContent = versionSelect.dataset.loadingLabel;
  versionSelect.replaceChildren(loadingOption);
  const response = await fetch(
    `/servers/version-options?server_type=${encodeURIComponent(typeSelect.value)}`,
  );
  versionSelect.innerHTML = await response.text();
}

typeSelect.addEventListener('change', loadVersions);
loadVersions();
