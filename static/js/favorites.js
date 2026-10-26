// Favorites: the admin's are stored on the server; visitors keep theirs in this browser only.
import { state } from './state.js';

const KEY = 'radar.favorites';

function load() {
  try {
    return new Set(JSON.parse(localStorage.getItem(KEY) || '[]'));
  } catch {
    return new Set();
  }
}

let local = load();

export function isFavorite(item) {
  return state.admin ? Boolean(item.favorite) : local.has(item.id);
}

export function toggleLocalFavorite(id) {
  if (local.has(id)) local.delete(id);
  else local.add(id);
  try {
    localStorage.setItem(KEY, JSON.stringify([...local]));
  } catch {
    /* storage blocked: favorites last until the page is closed */
  }
}

export function reloadLocal() {
  local = load();
}
