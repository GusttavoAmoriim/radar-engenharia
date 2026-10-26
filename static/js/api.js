// JSON API client. State-changing requests carry the CSRF token of the session.
let csrf = '';

export function setCsrf(token) {
  csrf = token || '';
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export async function api(url, options = {}) {
  const method = options.method || 'GET';
  const headers = { ...(options.headers || {}) };
  if (method !== 'GET') {
    headers['Content-Type'] = 'application/json';
    if (csrf) headers['X-CSRF-Token'] = csrf;
  }
  const response = await fetch(url, { credentials: 'same-origin', ...options, headers });
  const data = await response.json().catch(() => ({ detail: 'Resposta inválida do servidor' }));
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : `Erro HTTP ${response.status}`;
    throw new ApiError(detail, response.status);
  }
  return data;
}

export const post = (url, body = {}) => api(url, { method: 'POST', body: JSON.stringify(body) });
export const patch = (url, body = {}) => api(url, { method: 'PATCH', body: JSON.stringify(body) });
