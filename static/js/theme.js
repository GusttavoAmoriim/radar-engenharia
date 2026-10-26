// Two themes (light/dark) plus "auto", which follows the device setting.
import { icon } from './icons.js';

const KEY = 'radar.theme';
const media = window.matchMedia('(prefers-color-scheme: dark)');
const listeners = new Set();

export function preference() {
  try {
    const value = localStorage.getItem(KEY);
    return value === 'light' || value === 'dark' ? value : 'auto';
  } catch {
    return 'auto';
  }
}

export function resolved() {
  const pref = preference();
  return pref === 'auto' ? (media.matches ? 'dark' : 'light') : pref;
}

export function setPreference(value) {
  try {
    if (value === 'light' || value === 'dark') localStorage.setItem(KEY, value);
    else localStorage.removeItem(KEY);
  } catch {
    /* storage blocked: applies to this page only */
  }
  apply(value);
}

function apply(value) {
  if (value === 'light' || value === 'dark') document.documentElement.dataset.theme = value;
  else delete document.documentElement.dataset.theme;
  listeners.forEach((fn) => fn(resolved(), preference()));
}

export function onChange(fn) {
  listeners.add(fn);
  fn(resolved(), preference());
}

export function toggle() {
  setPreference(resolved() === 'dark' ? 'light' : 'dark');
}

export function bindToggle(button) {
  onChange((current) => {
    const next = current === 'dark' ? 'claro' : 'escuro';
    button.innerHTML = icon(current === 'dark' ? 'sun' : 'moon');
    button.setAttribute('aria-label', `Mudar para o tema ${next}`);
    button.title = `Tema ${next}`;
  });
  button.addEventListener('click', toggle);
}

media.addEventListener('change', () => {
  if (preference() === 'auto') apply('auto');
});
