window.talosToast = function (message, error = false) {
  if (!message) return;
  const region = document.querySelector('#toast-region');
  const toast = document.createElement('div');
  toast.className = `toast ${error ? 'toast-error' : 'toast-success'}`;
  const icon = document.createElement('span');
  icon.className = 'toast-icon';
  icon.textContent = error ? '!' : '✓';
  const text = document.createElement('span');
  text.textContent = message;
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'toast-close';
  close.setAttribute('aria-label', 'Close notification');
  close.textContent = '×';
  close.addEventListener('click', () => toast.remove());
  toast.append(icon, text, close);
  region.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('toast-visible'));
  setTimeout(() => {
    toast.classList.remove('toast-visible');
    setTimeout(() => toast.remove(), 220);
  }, error ? 7000 : 4200);
};

window.talosOperation = function (title, initialStage) {
  const region = document.querySelector('#toast-region');
  const toast = document.createElement('div');
  toast.className = 'toast operation-toast';
  const spinner = document.createElement('span');
  spinner.className = 'operation-spinner';
  const content = document.createElement('span');
  const heading = document.createElement('strong');
  const stage = document.createElement('small');
  heading.textContent = title;
  stage.textContent = initialStage;
  content.append(heading, stage);
  toast.append(spinner, content);
  region.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('toast-visible'));
  const finish = (message, error) => {
    spinner.className = `operation-result ${error ? 'error' : 'success'}`;
    spinner.textContent = error ? '!' : '✓';
    stage.textContent = message;
    setTimeout(() => {
      toast.classList.remove('toast-visible');
      setTimeout(() => toast.remove(), 220);
    }, error ? 6500 : 1800);
  };
  return {
    stage(message) { stage.textContent = message; },
    success(message) { finish(message, false); },
    error(message) { finish(message, true); },
  };
};

document.querySelectorAll('[data-local-tabs]').forEach(tabset => {
  const buttons = tabset.querySelectorAll('[data-local-tab]');
  const panels = tabset.parentElement.querySelectorAll('[data-local-panel]');
  buttons.forEach(button => button.addEventListener('click', () => {
    buttons.forEach(item => item.setAttribute('aria-selected', String(item === button)));
    panels.forEach(panel => {
      panel.classList.toggle('hidden', panel.dataset.localPanel !== button.dataset.localTab);
    });
  }));
});

const appFrame = document.querySelector('.app-frame');
const menuToggle = document.querySelector('.mobile-menu-toggle');
const closeNavigation = () => {
  appFrame?.classList.remove('navigation-open');
  menuToggle?.setAttribute('aria-expanded', 'false');
};
menuToggle?.addEventListener('click', () => {
  const open = !appFrame.classList.contains('navigation-open');
  appFrame.classList.toggle('navigation-open', open);
  menuToggle.setAttribute('aria-expanded', String(open));
});
document.querySelector('.sidebar-close')?.addEventListener('click', closeNavigation);
document.querySelector('.sidebar-scrim')?.addEventListener('click', closeNavigation);

if (document.body.dataset.errorMessage) {
  window.talosToast(document.body.dataset.errorMessage, true);
  const url = new URL(window.location.href);
  url.searchParams.delete('error');
  history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
}
