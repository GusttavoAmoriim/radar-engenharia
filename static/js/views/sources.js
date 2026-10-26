import { esc, safeUrl } from '../dom.js';
import { CANDIDATE_LABELS, dateTime } from '../format.js';
import { icon } from '../icons.js';
import { state } from '../state.js';

let root;
const MODE_LABELS = {
  watch: 'Monitor de alterações da página',
  gazette_search: 'Busca nos diários oficiais municipais',
};

export function mount(container) {
  root = container;
}

function sourceState(source, log) {
  if (source.pacing?.blocked) return ['Acesso suspenso', 'danger'];
  if (!log) return ['Não testada', 'closed'];
  if (log.state === 'running') return ['Executando', 'upcoming'];
  if (log.state === 'blocked') return ['Acesso suspenso', 'danger'];
  if (log.state === 'failed' && String(log.error).startsWith('Cobertura PARCIAL')) return ['Cobertura parcial', 'verify'];
  if (log.state === 'failed') return ['Falha', 'danger'];
  return [source.mode === 'watch' ? 'Página acessível' : 'Coleta OK', 'open'];
}

function sourceRow(source, health) {
  const log = health.find((h) => h.source === source.name);
  if (source.enabled === false) {
    return `<article class="row">
      <div class="row-head"><strong>${esc(source.name)}</strong><span class="badge badge-closed">Desligada</span></div>
      <p>Desligada em sources.yaml. Não é consultada até ser ligada de novo.</p>
      <p class="meta">${esc([source.agency, source.uf].filter(Boolean).join(' · '))}</p>
    </article>`;
  }
  const [label, tone] = sourceState(source, log);
  const mode = MODE_LABELS[source.mode] || 'Busca de editais';
  let detail = 'Ainda não consultada.';
  if (source.pacing?.blocked) {
    detail = `O site recusou o acesso automático (HTTP ${esc(source.pacing.status)}). Nova tentativa após ${esc(dateTime(source.pacing.until))}.`;
  } else if (log?.error) {
    detail = esc(log.error);
  } else if (log) {
    detail = source.mode === 'gazette_search'
      ? `Diários com concurso de engenharia: ${log.found} · novos: ${log.added}`
      : `Editais examinados: ${log.found} · novos: ${log.added}`;
  }
  return `<article class="row">
    <div class="row-head"><strong>${esc(source.name)}</strong><span class="badge badge-${tone}">${label}</span></div>
    <p>${detail}</p>
    <p class="meta">${esc([source.agency, source.uf].filter(Boolean).join(' · '))}${source.agency || source.uf ? ' · ' : ''}${mode}${log ? ` · última consulta ${esc(dateTime(log.finished_at || log.started_at))}` : ''} · <a href="${safeUrl(source.mode === 'gazette_search' ? 'https://queridodiario.ok.org.br/' : source.url)}" target="_blank" rel="noopener noreferrer">${source.mode === 'gazette_search' ? 'Abrir Querido Diário ↗' : 'Abrir fonte oficial ↗'}</a></p>
  </article>`;
}

function candidateRow(candidate) {
  const tone = candidate.state === 'edital_eng' ? 'open' : candidate.state === 'gazette_eng' ? 'upcoming' : candidate.state === 'fetch_failed' ? 'danger' : 'verify';
  return `<article class="row">
    <div class="row-head"><strong>${esc(candidate.title)}</strong><span class="badge badge-${tone}">${esc(CANDIDATE_LABELS[candidate.state] || candidate.state)}</span></div>
    <p>${esc(candidate.detail)}</p>
    <p class="meta">${esc(candidate.source)} · visto em ${esc(dateTime(candidate.last_seen))}${candidate.notice_url ? ` · <a href="${safeUrl(candidate.notice_url)}" target="_blank" rel="noopener noreferrer">Documento oficial ↗</a>` : ''}</p>
  </article>`;
}

export function render() {
  if (!root) return;
  const data = state.sources;
  const health = data.health || [];
  const catalog = data.catalog || [];
  root.innerHTML = `
    <div class="section-head">
      <div><h2 class="section-title">Cobertura das fontes</h2><p class="lead">${esc(data.cron || 'Varredura a cada 3 horas')}. Falhas e cobertura parcial ficam visíveis aqui.</p></div>
      ${data.running ? `<span class="badge badge-upcoming">${icon('refresh')}Varredura em andamento</span>` : ''}
    </div>
    <div class="list">${catalog.map((s) => sourceRow(s, health)).join('') || '<div class="empty">Nenhuma fonte configurada.</div>'}</div>
    <div class="admin-only view">
      <div class="section-head"><h2 class="section-title">Editais encontrados para triagem</h2></div>
      <div class="list">${state.candidates.map(candidateRow).join('') || `<div class="empty">${icon('inbox')}<span>Nenhum edital detectado automaticamente ainda.</span></div>`}</div>
    </div>`;
}
