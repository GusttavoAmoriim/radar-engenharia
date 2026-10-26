// Entry point: authentication, navigation (#hash routes), data loading and periodic refresh.
import { ApiError, api, post, setCsrf } from './api.js';
import { $, $$, esc, toast } from './dom.js';
import { icon } from './icons.js';
import { state } from './state.js';
import * as theme from './theme.js';
import * as alertsView from './views/alerts.js';
import * as opportunitiesView from './views/opportunities.js';
import * as settingsView from './views/settings.js';
import * as sourcesView from './views/sources.js';

const ROUTES = [
  { id: 'concursos', label: 'Concursos', icon: 'radar', view: opportunitiesView },
  { id: 'alertas', label: 'Alertas', icon: 'bell', view: alertsView },
  { id: 'fontes', label: 'Fontes', icon: 'database', view: sourcesView },
  { id: 'configuracoes', label: 'Configurações', icon: 'settings', view: settingsView },
];

function currentRoute() {
  const id = location.hash.replace('#', '');
  return ROUTES.find((r) => r.id === id) || ROUTES[0];
}

function navigate() {
  const route = currentRoute();
  if (location.hash === '#entrar') return;
  for (const r of ROUTES) $(`#view-${r.id}`).classList.toggle('hidden', r !== route);
  for (const link of $$('.nav-link')) {
    if (link.dataset.route === route.id) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  $('#pageTitle').textContent = route.label;
  document.title = `${route.label} · ${appName()}`;
}

function buildNav() {
  $('#nav').innerHTML = ROUTES.map(
    (r) => `<a class="nav-link" href="#${r.id}" data-route="${r.id}">${icon(r.icon)}<span>${esc(r.label)}</span></a>`,
  ).join('');
}

const appName = () => document.querySelector('meta[name=app-name]')?.content || 'Radar Engenharia';

/** Decide what to show: the app (admin or public visitor) or the login screen. */
function render() {
  const wantsLogin = location.hash === '#entrar';
  const showLogin = !state.admin && (!state.publicMode || wantsLogin);
  document.body.classList.toggle('is-admin', state.admin);
  $('#appView').classList.toggle('hidden', showLogin);
  $('#loginView').classList.toggle('hidden', !showLogin);
  $('#loginBack').classList.toggle('hidden', !state.publicMode);
  if (showLogin) {
    document.title = `Entrar · ${appName()}`;
    $('#loginForm input[type=password]').focus();
  } else {
    if (wantsLogin) history.replaceState(null, '', '#concursos');
    navigate();
  }
}

export async function loadAll() {
  if (!state.admin && !state.publicMode) return;
  try {
    const requests = [api('/api/opportunities'), api('/api/alerts'), api('/api/sources')];
    if (state.admin) requests.push(api('/api/candidates'));
    const [opportunities, alerts, sources, candidates] = await Promise.all(requests);
    state.items = opportunities.items;
    state.alerts = alerts.items;
    state.sources = sources;
    state.candidates = candidates ? candidates.items : [];
    state.loaded = true;
    for (const r of ROUTES) r.view.render();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      state.admin = false;
      return render();
    }
    toast(error.message);
  }
}

async function login(event) {
  event.preventDefault();
  const form = event.currentTarget;
  $('#loginError').textContent = '';
  try {
    const result = await post('/api/auth/login', {
      password: form.elements.password.value,
      code: form.elements.code.value,
      remember: form.elements.remember.checked,
    });
    if (result.mfa_required) {
      $('#otpField').classList.remove('hidden');
      form.elements.code.required = true;
      form.elements.code.focus();
      return;
    }
    setCsrf(result.csrf);
    state.admin = true;
    state.mfa = result.mfa_enabled;
    form.reset();
    $('#otpField').classList.add('hidden');
    if (location.hash === '#entrar') history.replaceState(null, '', '#concursos');
    render();
    await loadAll();
  } catch (error) {
    $('#loginError').textContent = error.message;
  }
}

async function logout() {
  try {
    await post('/api/auth/logout');
  } finally {
    setCsrf('');
    state.admin = false;
    $('#loginForm').reset();
    $('#otpField').classList.add('hidden');
    render();
    await loadAll();
  }
}

async function init() {
  buildNav();
  for (const r of ROUTES) r.view.mount($(`#view-${r.id}`), loadAll);
  for (const slot of $$('[data-icon]')) slot.outerHTML = icon(slot.dataset.icon);
  theme.bindToggle($('#themeToggle'));
  $('#loginForm').addEventListener('submit', login);
  $('#logoutBtn').addEventListener('click', logout);
  window.addEventListener('hashchange', render);
  window.addEventListener('scroll', () => $('#topbar').classList.toggle('scrolled', window.scrollY > 4), { passive: true });
  try {
    const status = await api('/api/auth/status');
    state.admin = status.authenticated;
    state.publicMode = status.public;
    state.mfa = Boolean(status.mfa_enabled);
    state.defaultUf = status.default_uf || '';
    setCsrf(status.csrf);
  } catch (error) {
    toast(error.message);
  }
  render();
  await loadAll();
  setInterval(() => {
    if (!document.hidden) loadAll();
  }, 90_000);
}

init();
