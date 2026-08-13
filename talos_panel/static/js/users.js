const usersPage = document.querySelector('.users-page');
if (usersPage.dataset.message) window.talosToast(usersPage.dataset.message);

const dialog = document.querySelector('#user-confirm-dialog');
const message = document.querySelector('#user-confirm-message');
let pending = null;

document.querySelectorAll('form[data-confirm]').forEach(form => {
  form.addEventListener('submit', event => {
    event.preventDefault();
    pending = form;
    message.textContent = form.dataset.confirm;
    dialog.showModal();
  });
});

document.querySelector('#user-confirm-submit').addEventListener('click', () => {
  if (pending) pending.submit();
});
