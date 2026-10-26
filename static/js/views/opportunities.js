import { patch, post } from '../api.js';
import { $, esc, safeUrl, toast } from '../dom.js';
import { STATUS_LABELS, dateTime, day, period, plural, salary, verifiedMessage } from '../format.js';
import { icon } from '../icons.js';
import { state } from '../state.js';
import { isFavorite, toggleLocalFavorite } from '../favorites.js';
import { openEditor } from './editor.js';

let root;
let refresh = async () => {};
let defaultApplied = false;

const STAGE_LABELS = {
  '': 'Sem etapa',
  interesse: 'Tenho interesse',
  inscrito: 'Inscrito',
  prova: 'Prova marcada',
  resultado: 'Aguardando resultado',
  desisti: 'Desisti',
};

/** Lowercase and without accents, so “sao paulo” finds “São Paulo” and “fiscal” finds “Fiscal”. */
const fold = (value) =>
  String(value ?? '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLocaleLowerCase('pt-BR');

const SORTS = {
  deadline: (a, b) => (a.days_left ?? 9999) - (b.days_left ?? 9999) || b.id - a.id,
  salary: (a, b) => (b.salary_max ?? b.salary_min ?? 0) - (a.salary_max ?? a.salary_min ?? 0),
  agency: (a, b) => fold(a.agency).localeCompare(fold(b.agency), 'pt-BR'),
  recent: (a, b) => b.id - a.id,
};

export function mount(container, onRefresh) {
  root = container;
  refresh = onRefresh;
  root.innerHTML = `
    <div class="stats" aria-label="Resumo">
      <div class="stat is-open"><span>Abertos comprovados</span><strong id="countOpen">0</strong></div>
      <div class="stat is-due"><span>Encerram em 7 dias</span><strong id="countDue">0</strong></div>
      <div class="stat"><span>A conferir</span><strong id="countPending">0</strong></div>
    </div>
    <div class="toolbar">
      <div class="toolbar-row">
        <div class="search">
          ${icon('search')}
          <label class="sr-only" for="search">Buscar</label>
          <input class="input" type="search" id="search" placeholder="Buscar cargo, órgão ou cidade" autocomplete="off">
        </div>
        <button class="btn admin-only" id="scanBtn" type="button">${icon('refresh')}<span>Verificar agora</span></button>
        <button class="btn btn-primary admin-only" id="addBtn" type="button">${icon('plus')}<span>Concurso</span></button>
      </div>
      <div class="filters">
        <label class="sr-only" for="status">Situação</label>
        <select class="select" id="status">
          <option value="all">Todas as situações</option>
          <option value="open">Inscrições abertas</option>
          <option value="upcoming">Inscrições em breve</option>
          <option value="verify">A conferir</option>
          <option value="closed">Encerrados</option>
          <option value="favorite">Favoritos</option>
        </select>
        <label class="sr-only" for="kind">Tipo</label>
        <select class="select" id="kind">
          <option value="all">Concursos e seleções</option>
          <option value="concurso">Só concursos públicos</option>
          <option value="pss">Só seleções temporárias (PSS)</option>
        </select>
        <label class="sr-only" for="region">Região</label>
        <select class="select" id="region">
          <option value="all">Todas as regiões</option>
          <option value="sp">Prova ou trabalho em SP</option>
          <option value="national">Nacional</option>
        </select>
        <label class="sr-only" for="uf">Estado</label>
        <select class="select" id="uf"><option value="all">Todos os estados</option></select>
        <label class="sr-only" for="sort">Ordenar por</label>
        <select class="select" id="sort">
          <option value="deadline">Prazo mais próximo</option>
          <option value="salary">Maior salário</option>
          <option value="agency">Órgão (A–Z)</option>
          <option value="recent">Mais recentes</option>
        </select>
        <div class="salary-filter" role="group" aria-labelledby="salaryTitle">
          <div class="salary-filter-head"><span id="salaryTitle">Salário</span><output id="salaryText" for="salaryMin salaryMax">Qualquer valor</output></div>
          <div class="dual-range">
            <div class="dual-range-fill" id="salaryFill"></div>
            <input type="range" id="salaryMin" min="${SALARY_MIN}" max="${SALARY_MAX}" step="1000" value="${SALARY_MIN}" aria-label="Salário mínimo">
            <input type="range" id="salaryMax" min="${SALARY_MIN}" max="${SALARY_MAX}" step="1000" value="${SALARY_MAX}" aria-label="Salário máximo">
          </div>
        </div>
      </div>
      <div class="section-head">
        <p class="scan-line">${icon('clock')}<span id="latestScan">Nenhuma varredura ainda</span></p>
        <p class="result-count" id="resultCount" aria-live="polite"></p>
      </div>
    </div>
    <div id="items" class="items" aria-busy="true">
      <div class="skeleton"></div><div class="skeleton"></div>
    </div>
    <p class="muted">Somente fontes oficiais. O sistema procura e confere o edital sozinho; o que ainda não foi conferido no edital aparece marcado como “não conferido”.</p>`;

  for (const id of ['search', 'status', 'kind', 'region', 'uf', 'sort']) {
    $(`#${id}`, root).addEventListener(id === 'search' ? 'input' : 'change', render);
  }
  for (const id of ['salaryMin', 'salaryMax']) {
    $(`#${id}`, root).addEventListener('input', (event) => {
      const low = $('#salaryMin', root);
      const high = $('#salaryMax', root);
      if (Number(low.value) > Number(high.value)) {
        if (event.target === low) high.value = low.value;
        else low.value = high.value;
      }
      render();
    });
  }
  $('#scanBtn', root).addEventListener('click', scan);
  $('#addBtn', root).addEventListener('click', () => openEditor(null, refresh));
  $('#items', root).addEventListener('click', onAction);
  $('#items', root).addEventListener('change', onStageChange);
}

const SALARY_MIN = 3000;
const SALARY_MAX = 50000;

const thousands = (value) => `R$ ${Number(value / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} mil`;

/** Slider band: null means no limit on that side (3 mil = no minimum, 50 mil+ = no maximum). */
function salaryBand() {
  const low = Number($('#salaryMin', root).value);
  const high = Number($('#salaryMax', root).value);
  return [low > SALARY_MIN ? low : null, high < SALARY_MAX ? high : null];
}

function paintSalary([low, high]) {
  const text =
    low == null && high == null
      ? 'Qualquer valor'
      : low == null
        ? `até ${thousands(high)}`
        : high == null
          ? `${thousands(low)} ou mais`
          : `${thousands(low)} a ${thousands(high)}`;
  $('#salaryText', root).textContent = text;
  const span = SALARY_MAX - SALARY_MIN;
  const from = ((Number($('#salaryMin', root).value) - SALARY_MIN) / span) * 100;
  const to = ((Number($('#salaryMax', root).value) - SALARY_MIN) / span) * 100;
  const fill = $('#salaryFill', root);
  fill.style.left = `${from}%`;
  fill.style.width = `${to - from}%`;
}

function inSalaryBand(item, [low, high]) {
  if (low == null && high == null) return true;
  const values = [item.salary_min, item.salary_max].filter((v) => v != null);
  if (!values.length) return false;
  return Math.max(...values) >= (low ?? 0) && Math.min(...values) <= (high ?? Infinity);
}

function facts(item) {
  const fact = (label, value, checked, extra = '') => {
    if (!value) return `<div><dt>${label}</dt><dd class="pending">A confirmar</dd></div>`;
    const tag = checked ? '' : ' <span class="unchecked">não conferido</span>';
    return `<div><dt>${label}</dt><dd class="${checked ? extra : 'is-unchecked'}">${esc(value)}${tag}</dd></div>`;
  };
  const verified = Boolean(item.document_verified);
  const exam = [item.exam_date ? day(item.exam_date) : '', item.exam_cities].filter(Boolean).join(' · ');
  return `<dl class="facts">
    ${fact('Salário do cargo', salary(item, { any: true }), Boolean(item.salary_verified), item.salary_highlight ? 'highlight' : '')}
    ${fact('Inscrições', period(item.registration_start, item.registration_end), verified)}
    ${fact('Prova', exam, verified)}
    ${fact('Lotação', item.work_cities, verified)}
  </dl>`;
}

function card(item) {
  const status = STATUS_LABELS[item.status] || item.status;
  const due = item.status === 'open' && item.days_left != null
    ? `<span class="badge badge-verify">${icon('clock')}${item.days_left === 0 ? 'Último dia' : `Encerra em ${plural(item.days_left, 'dia', 'dias')}`}</span>`
    : '';
  const temporary = item.type === 'pss'
    ? `<span class="badge badge-temp" title="Contratação por prazo determinado, sem estabilidade. Não é concurso público.">${icon('clock')}Temporário (PSS)</span>`
    : '';
  const proof = item.document_verified
    ? `<span class="badge badge-ok">${icon('check')}Edital validado</span>`
    : '<span class="badge">Sem prova documental</span>';
  const links = [
    item.notice_url && `<a class="link-out" href="${safeUrl(item.notice_url)}" target="_blank" rel="noopener noreferrer">${icon('file')}Edital</a>`,
    item.official_url && `<a class="link-out" href="${safeUrl(item.official_url)}" target="_blank" rel="noopener noreferrer">${icon('external')}Site oficial</a>`,
    item.status === 'open' && item.apply_url && item.document_verified &&
      `<a class="btn btn-primary btn-sm" href="${safeUrl(item.apply_url)}" target="_blank" rel="noopener noreferrer">Inscrever-se ${icon('external')}</a>`,
  ].filter(Boolean).join('');
  const excerpt = (item.proof?.role_excerpt || '').slice(0, 280);
  const check = item.last_check;
  const audit = item.proof
    ? `Edital ${esc(item.proof.sha256.slice(0, 16))}… verificado em ${esc(dateTime(item.proof.checked_at))}`
    : check && !check.ok
      ? `Última tentativa de validação (${esc(dateTime(check.at))}): ${esc(check.message)}`
      : 'Edital ainda não verificado; o sistema tenta validar sozinho a cada coleta';
  return `<article class="opp" data-status="${esc(item.status)}" data-id="${item.id}">
    <div class="opp-head">
      <div>
        <div class="badges"><span class="badge badge-${esc(item.status)}">${esc(status)}</span>${due}${temporary}${proof}${item.applied ? `<span class="badge badge-info">${icon('check')}Inscrito</span>` : ''}</div>
        <h3 class="opp-title">${esc(item.title)}</h3>
        <p class="opp-sub">${esc(item.agency || item.source || 'Órgão não informado')} · ${esc(item.position || 'Cargo de engenharia a especificar')}</p>
      </div>
      <button class="icon-btn" type="button" data-action="favorite" aria-pressed="${isFavorite(item) ? 'true' : 'false'}" aria-label="${isFavorite(item) ? 'Remover dos favoritos' : 'Favoritar'}">${icon('star')}</button>
    </div>
    ${facts(item)}
    <div class="opp-foot">
      <div class="opp-links">${links || '<span class="muted">Sem links oficiais</span>'}</div>
      <div class="opp-admin admin-only">
        <button class="btn btn-sm" type="button" data-action="edit">${icon('edit')}Editar</button>
        <button class="btn btn-sm" type="button" data-action="verify">${icon('shield')}${item.document_verified ? 'Revalidar' : 'Validar edital'}</button>
        <button class="btn btn-sm" type="button" data-action="applied">${item.applied ? 'Desmarcar inscrição' : 'Marcar inscrição'}</button>
        <label class="stage-field"><span>Minha etapa</span>
          <select class="select" data-stage-select="${item.id}">${Object.entries(STAGE_LABELS).map(([v, l]) => `<option value="${v}" ${(item.stage || '') === v ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>
        </label>
      </div>
    </div>
    <details>
      <summary>Observações e auditoria</summary>
      ${item.notes ? `<p>${esc(item.notes)}</p>` : ''}
      <p class="muted">Origem: ${esc(item.source || '—')} · ${audit}</p>
      ${excerpt ? `<p class="muted">Trecho do edital: “${esc(excerpt)}”</p>` : ''}
    </details>
  </article>`;
}

export function render() {
  if (!root) return;
  const visible = state.items.filter((item) => !item.dismissed);
  $('#countOpen', root).textContent = visible.filter((i) => i.status === 'open').length;
  $('#countDue', root).textContent = visible.filter((i) => i.status === 'open' && i.days_left != null && i.days_left <= 7).length;
  $('#countPending', root).textContent = visible.filter((i) => !i.document_verified).length;

  fillStates(visible);
  const query = fold($('#search', root).value.trim());
  const status = $('#status', root).value;
  const region = $('#region', root).value;
  const kind = $('#kind', root).value;
  const uf = $('#uf', root).value;
  const sort = $('#sort', root).value;
  const band = salaryBand();
  paintSalary(band);
  const list = visible
    .filter((i) =>
      (status === 'all' || (status === 'favorite' ? isFavorite(i) : i.status === status)) &&
      (kind === 'all' || (i.type || 'concurso') === kind) &&
      (region === 'all' || (region === 'sp' ? i.eligible_sp : i.national)) &&
      (uf === 'all' || i.state === uf || i.national || (uf === 'SP' && i.eligible_sp)) &&
      inSalaryBand(i, band) &&
      (!query || fold([i.title, i.agency, i.position, i.work_cities, i.exam_cities].join(' ')).includes(query)),
    )
    .sort((a, b) => Number(isFavorite(b)) - Number(isFavorite(a)) || (SORTS[sort] || SORTS.deadline)(a, b));

  const items = $('#items', root);
  items.setAttribute('aria-busy', 'false');
  $('#resultCount', root).textContent = state.loaded ? plural(list.length, 'concurso', 'concursos') : '';
  items.innerHTML = list.length
    ? list.map(card).join('')
    : `<div class="empty">${icon('inbox')}<strong>Nenhum concurso com estes filtros</strong><span>Limpe a busca ou veja a aba Fontes para conferir a cobertura.</span></div>`;

  const health = state.sources.health || [];
  const failed = health.filter((h) => h.state === 'failed' || h.state === 'blocked').length;
  const latest = [...health].sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)))[0];
  $('#latestScan', root).textContent = latest
    ? `Última varredura: ${dateTime(latest.started_at)}${failed ? ` · ${plural(failed, 'fonte com problema', 'fontes com problema')}` : ''}`
    : 'Nenhuma varredura ainda';
}

async function onAction(event) {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const id = Number(button.closest('[data-id]').dataset.id);
  const item = state.items.find((i) => i.id === id);
  if (!item) return;
  try {
    switch (button.dataset.action) {
      case 'favorite':
        if (!state.admin) {
          toggleLocalFavorite(id);
          render();
          return;
        }
        await patch(`/api/opportunities/${id}`, { favorite: item.favorite ? 0 : 1 });
        break;
      case 'applied':
        await patch(`/api/opportunities/${id}`, { applied: item.applied ? 0 : 1 });
        break;
      case 'edit':
        openEditor(item, refresh);
        return;
      case 'verify':
        toast('Procurando o edital oficial e conferindo cargo, datas e salário…');
        toast(verifiedMessage(await post(`/api/opportunities/${id}/verify`)));
        break;
      default:
        return;
    }
    await refresh();
  } catch (error) {
    toast(error.message);
  }
}

async function scan() {
  const button = $('#scanBtn', root);
  button.disabled = true;
  try {
    await post('/api/scan');
    toast('Varredura iniciada. Acompanhe em Fontes.');
    location.hash = '#fontes';
    setTimeout(refresh, 4000);
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
}

/** Fill the state list from the visible items and preselect the configured UF once. */
function fillStates(visible) {
  const select = $('#uf', root);
  const current = select.value;
  const ufs = [...new Set([...visible.map((i) => i.state).filter(Boolean), state.defaultUf].filter(Boolean))].sort();
  select.innerHTML =
    '<option value="all">Todos os estados</option>' + ufs.map((u) => `<option value="${esc(u)}">${esc(u)}</option>`).join('');
  if (!defaultApplied && state.loaded) {
    defaultApplied = true;
    if (state.defaultUf && ufs.includes(state.defaultUf)) select.value = state.defaultUf;
    return;
  }
  select.value = [...select.options].some((o) => o.value === current) ? current : 'all';
}

/** Admin-only: the personal stage of a contest. Stored privately; visitors never receive it. */
async function onStageChange(event) {
  const select = event.target.closest('[data-stage-select]');
  if (!select) return;
  try {
    await patch(`/api/opportunities/${select.dataset.stageSelect}`, { stage: select.value });
    toast(`Etapa: ${STAGE_LABELS[select.value]}`);
    await refresh();
  } catch (error) {
    toast(error.message);
  }
}
