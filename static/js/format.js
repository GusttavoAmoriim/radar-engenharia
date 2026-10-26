// Formatting and human-readable labels (pt-BR).

export const STATUS_LABELS = {
  open: 'Inscrições abertas',
  upcoming: 'Inscrições em breve',
  closed: 'Encerrado',
  verify: 'A conferir',
  announced: 'Anunciado',
  suspended: 'Suspenso',
  cancelled: 'Cancelado',
};

export const ALERT_LABELS = {
  new: 'Novo edital',
  site_changed: 'Alteração',
  deadline: 'Prazo',
  coverage: 'Cobertura',
};

export const CANDIDATE_LABELS = {
  edital_eng: 'Edital de engenharia encontrado',
  gazette_eng: 'Achado no Diário Oficial',
  needs_review: 'Precisa de revisão',
  fetch_failed: 'Falha ao baixar',
  pending: 'Pendente',
};

/** 'YYYY-MM-DD' -> '15/10/2026' */
export function day(iso) {
  if (!iso) return '';
  const date = new Date(`${String(iso).slice(0, 10)}T12:00:00`);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('pt-BR');
}

/** ISO timestamp -> '15/10/2026 09:00' */
export function dateTime(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso).replace('T', ' ').slice(0, 16);
  return date.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
}

export function money(value) {
  if (value == null || value === '') return '';
  return Number(value).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 2 });
}

/** Salary as 'R$ x' or 'R$ x a R$ y'. Only verified values unless { any: true }. */
export function salary(item, { any = false } = {}) {
  if (!item.salary_verified && !any) return '';
  const low = item.salary_min ?? item.salary_max;
  const high = item.salary_max ?? item.salary_min;
  if (low == null) return '';
  return low === high ? money(low) : `${money(low)} a ${money(high)}`;
}

/** Toast text after a validation; lists facts the edital did not support. */
export function verifiedMessage(item) {
  const missing = item?.warnings || [];
  return missing.length
    ? `Edital validado. Não encontrados no edital (removidos e guardados nas observações): ${missing.join(', ')}.`
    : 'Edital validado e registrado.';
}

export function period(start, end) {
  if (start && end) return `${day(start)} a ${day(end)}`;
  if (end) return `até ${day(end)}`;
  if (start) return `a partir de ${day(start)}`;
  return '';
}

export function plural(count, one, many) {
  return `${count} ${count === 1 ? one : many}`;
}
