import { esc } from '../dom.js';
import { ALERT_LABELS, dateTime } from '../format.js';
import { icon } from '../icons.js';
import { state } from '../state.js';

const TONES = { new: 'open', site_changed: 'verify', deadline: 'upcoming', coverage: 'danger' };
let root;

export function mount(container) {
  root = container;
}

export function render() {
  if (!root) return;
  const rows = state.alerts.map((alert) => `<article class="row">
      <div class="row-head"><span class="badge badge-${TONES[alert.kind] || 'closed'}">${esc(ALERT_LABELS[alert.kind] || alert.kind)}</span><time datetime="${esc(alert.created_at)}">${esc(dateTime(alert.created_at))}</time></div>
      <p>${esc(alert.text)}</p>
    </article>`);
  root.innerHTML = `
    <div class="section-head"><div><h2 class="section-title">Alertas</h2><p class="lead">Editais novos, alterações, prazos e problemas de cobertura.</p></div></div>
    <div class="list">${rows.join('') || `<div class="empty">${icon('bell')}<strong>Sem alertas por enquanto</strong><span>Eles aparecem aqui depois das varreduras.</span></div>`}</div>`;
}
