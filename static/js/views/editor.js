import { api, post } from '../api.js';
import { $, esc, toast } from '../dom.js';
import { verifiedMessage } from '../format.js';

const TEXT = [
  ['title', 'Nome do concurso', 'wide', 'text', true],
  ['agency', 'Órgão', '', 'text'],
  ['position', 'Cargo específico (Engenheiro Civil ou Mecânico)', '', 'text', true],
  ['salary_min', 'Salário mínimo do cargo', '', 'number'],
  ['salary_max', 'Salário máximo do cargo', '', 'number'],
  ['registration_start', 'Início das inscrições', '', 'date'],
  ['registration_end', 'Fim das inscrições', '', 'date'],
  ['exam_date', 'Data da prova', '', 'date'],
  ['state', 'UF de trabalho', '', 'text'],
  ['exam_cities', 'Local da prova', '', 'text'],
  ['work_cities', 'Local de trabalho', '', 'text'],
  ['official_url', 'Página oficial', 'wide', 'url', true],
  ['notice_url', 'Edital oficial (link direto do documento)', 'wide', 'url', true],
  ['apply_url', 'Página de inscrição', 'wide', 'url'],
];
const CHECKS = [
  ['exam_in_sp', 'Prova em SP'],
  ['work_in_sp', 'Trabalho em SP'],
  ['national', 'Nacional'],
];

let current = null;
let done = async () => {};

function build(dialog) {
  dialog.innerHTML = `<form method="dialog" id="editForm">
    <div class="dialog-head"><h2 id="editorTitle">Concurso</h2><button class="btn btn-ghost" type="button" data-close>Fechar</button></div>
    <div class="dialog-body">
      ${TEXT.map(([name, label, cls, type, required]) => `<label class="field ${cls}">${label}
        <input class="input" name="${name}" type="${type}" ${type === 'number' ? 'step="0.01" min="0"' : ''} ${required ? 'required' : ''}></label>`).join('')}
      <div class="wide checks">${CHECKS.map(([name, label]) => `<label class="check"><input type="checkbox" name="${name}"> ${label}</label>`).join('')}</div>
      <div class="wide suggest-row" id="suggestRow">
        <button class="btn btn-ghost" type="button" id="suggestBtn">Sugerir campos a partir do edital</button>
        <div class="suggest-box hidden" id="suggestBox" role="status" aria-live="polite"></div>
      </div>
      <label class="field wide">Observações<textarea class="textarea" name="notes" rows="3"></textarea></label>
      <p class="wide muted">Salvar não confirma nada: use “Validar edital” para conferir os dados no documento oficial.</p>
      <p class="wide form-error" id="editError" role="alert"></p>
    </div>
    <div class="dialog-foot"><button class="btn" type="button" data-close>Cancelar</button><button class="btn btn-primary" type="submit">Salvar</button></div>
  </form>`;
  dialog.addEventListener('click', (event) => {
    if (event.target.closest('[data-close]') || event.target === dialog) dialog.close();
  });
  $('#editForm', dialog).addEventListener('submit', save);
  $('#suggestBtn', dialog).addEventListener('click', suggest);
}

export function openEditor(item, onSaved) {
  const dialog = $('#editor');
  if (!dialog.firstChild) build(dialog);
  current = item;
  done = onSaved;
  const form = $('#editForm', dialog);
  form.reset();
  $('#editorTitle', dialog).textContent = item ? 'Editar concurso' : 'Adicionar concurso';
  $('#editError', dialog).textContent = '';
  $('#suggestRow', dialog).classList.toggle('hidden', !item);
  $('#suggestBox', dialog).classList.add('hidden');
  $('#suggestBox', dialog).innerHTML = '';
  if (item) {
    for (const [name] of TEXT) form.elements[name].value = item[name] ?? '';
    for (const [name] of CHECKS) form.elements[name].checked = Boolean(item[name]);
    form.elements.notes.value = item.notes ?? '';
  }
  dialog.showModal();
  form.elements.title.focus();
}

async function save(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {};
  for (const [name, , , type] of TEXT) {
    const value = form.elements[name].value.trim();
    payload[name] = type === 'number' ? (value === '' ? null : Number(value)) : value || null;
  }
  for (const [name] of CHECKS) payload[name] = form.elements[name].checked ? 1 : 0;
  payload.notes = form.elements.notes.value.trim() || null;
  try {
    const saved = await api(current ? `/api/opportunities/${current.id}` : '/api/opportunities', {
      method: current ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    });
    $('#editor').close();
    await done();
    await validateAfterSave(saved);
  } catch (error) {
    $('#editError').textContent = error.message;
  }
}

/** Saving is enough: look for the official edital and validate right away. */
async function validateAfterSave(saved) {
  if (!saved?.id || !saved.position || !(saved.notice_url || saved.official_url || saved.apply_url)) {
    toast('Salvo. Informe o cargo de engenharia e um link oficial para o sistema validar o edital.');
    return;
  }
  toast('Salvo. Procurando o edital oficial e conferindo…');
  try {
    toast(verifiedMessage(await post(`/api/opportunities/${saved.id}/verify`)));
  } catch (error) {
    toast(`Salvo, mas o edital não foi validado: ${error.message}`);
  }
  await done();
}

const labelOf = (name) => TEXT.find(([field]) => field === name)?.[1] ?? name;

/** Ask the server to read the official notice. Fills only empty fields and never saves. */
async function suggest() {
  const dialog = $('#editor');
  const form = $('#editForm', dialog);
  const box = $('#suggestBox', dialog);
  const button = $('#suggestBtn', dialog);
  button.disabled = true;
  button.textContent = 'Lendo o edital…';
  try {
    const result = await post(`/api/opportunities/${current.id}/suggest`);
    const entries = Object.entries(result.suggestions);
    if (!entries.length) {
      box.innerHTML = '<p class="muted">Nenhuma sugestão segura encontrada no texto do edital.</p>';
    } else {
      const rows = entries.map(([name, { value, snippet }]) => {
        const field = form.elements[name];
        const filled = field && field.value.trim() !== '';
        if (field && !filled) field.value = value;
        return `<li><strong>${esc(labelOf(name))}:</strong> ${esc(value)}
          ${filled ? '<em class="muted">(já preenchido, mantido)</em>' : '<em class="muted">(preenchido, confira)</em>'}
          <span class="meta">“${esc(snippet)}”</span></li>`;
      });
      box.innerHTML = `<p class="muted">${esc(result.note)}</p><ul>${rows.join('')}</ul>`;
    }
    box.classList.remove('hidden');
  } catch (error) {
    box.innerHTML = `<p class="form-error">${esc(error.message)}</p>`;
    box.classList.remove('hidden');
  } finally {
    button.disabled = false;
    button.textContent = 'Sugerir campos a partir do edital';
  }
}
