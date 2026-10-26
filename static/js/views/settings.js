import { api, post } from '../api.js';
import { $, esc, toast } from '../dom.js';
import { dateTime } from '../format.js';
import { icon } from '../icons.js';
import { state } from '../state.js';
import * as theme from '../theme.js';

let root;

export function mount(container) {
  root = container;
  root.innerHTML = `
    <div class="settings-grid">
      <section class="panel">
        <h3>Aparência</h3>
        <p class="muted">Escolha o tema claro ou escuro. “Automático” segue o tema do seu dispositivo.</p>
        <div class="segmented" role="group" aria-label="Tema" id="themeChoice">
          <button type="button" data-theme-choice="light">${icon('sun')}Claro</button>
          <button type="button" data-theme-choice="dark">${icon('moon')}Escuro</button>
          <button type="button" data-theme-choice="auto">${icon('monitor')}Automático</button>
        </div>
      </section>
      <section class="panel admin-only" id="passwordPanel">
        <h3>Senha do administrador</h3>
        <p class="muted">Mínimo de 12 caracteres. Ao trocar, os outros dispositivos são desconectados.</p>
        <form id="passwordForm" class="form-grid">
          <label class="field">Senha atual<input class="input" type="password" id="pwCurrent" autocomplete="current-password" required></label>
          <label class="field">Nova senha<input class="input" type="password" id="pwNew" autocomplete="new-password" minlength="12" required></label>
          <label class="field hidden" id="pwCodeField">Código do autenticador<input class="input" id="pwCode" autocomplete="one-time-code"></label>
          <div class="form-actions"><button class="btn btn-primary" type="submit">Trocar senha</button></div>
        </form>
      </section>
      <section class="panel admin-only" id="alertsPanel">
        <h3>Avisos por e-mail ou Telegram</h3>
        <p class="muted">Envia uma mensagem de teste pelos canais configurados no .env (SMTP_* ou TELEGRAM_*). Não altera os alertas.</p>
        <div class="form-actions"><button class="btn" type="button" id="testAlerts">Enviar aviso de teste</button></div>
      </section>
      <section class="panel admin-only" id="devicesPanel">
        <h3>Dispositivos conectados</h3>
        <p class="muted">Sessões abertas neste radar. Encerre as que você não reconhece.</p>
        <div id="deviceList" class="device-list"></div>
        <div class="form-actions">
          <button class="btn btn-ghost" type="button" id="revokeOthers">Encerrar as outras sessões</button>
          <button class="btn btn-ghost" type="button" id="revokeTrusted">Esquecer dispositivos confiáveis</button>
        </div>
        <p class="muted" id="trustedInfo"></p>
        <h4>Atividade recente</h4>
        <ul id="eventList" class="event-list"></ul>
      </section>
      <section class="panel admin-only" id="mfaPanel">
        <h3>Verificação em duas etapas (MFA)</h3>
        <p class="muted" id="mfaStatus"></p>
        <form id="mfaSetupForm" class="form-grid">
          <label class="field">Confirme sua senha<input class="input" type="password" id="mfaPassword" autocomplete="current-password" required></label>
          <div class="form-actions"><button class="btn btn-primary" type="submit">${icon('shield')}Configurar aplicativo autenticador</button></div>
        </form>
        <div id="mfaQr" class="qr hidden">
          <img id="qrImage" alt="QR Code para o aplicativo autenticador">
          <p class="muted">Ou digite a chave manualmente: <code id="manualSecret"></code></p>
          <form id="mfaConfirmForm" class="form-grid">
            <label class="field">Código de 6 dígitos do aplicativo<input class="input" required id="confirmCode" inputmode="numeric" maxlength="6" placeholder="000000"></label>
            <div class="form-actions"><button class="btn btn-primary" type="submit">Ativar MFA</button></div>
          </form>
        </div>
        <div id="recovery" class="hidden">
          <p><strong>Guarde estes códigos de recuperação agora.</strong> Eles aparecem só uma vez.</p>
          <pre class="codes" id="recoveryCodes"></pre>
        </div>
        <form id="mfaDisableForm" class="form-grid hidden">
          <label class="field">Senha<input class="input" id="disablePassword" type="password" autocomplete="current-password" required></label>
          <label class="field">Código do aplicativo ou de recuperação<input class="input" id="disableCode" required></label>
          <div class="form-actions"><button class="btn btn-danger" type="submit">Desativar MFA</button></div>
        </form>
      </section>
    </div>`;

  theme.onChange((_, pref) => {
    for (const button of root.querySelectorAll('[data-theme-choice]')) {
      button.setAttribute('aria-pressed', String(button.dataset.themeChoice === pref));
    }
  });
  $('#themeChoice', root).addEventListener('click', (event) => {
    const button = event.target.closest('[data-theme-choice]');
    if (button) theme.setPreference(button.dataset.themeChoice);
  });
  $('#passwordForm', root).addEventListener('submit', changePassword);
  $('#testAlerts', root).addEventListener('click', testAlerts);
  $('#deviceList', root).addEventListener('click', onDeviceClick);
  $('#revokeOthers', root).addEventListener('click', revokeOthers);
  $('#revokeTrusted', root).addEventListener('click', revokeTrusted);
  $('#mfaSetupForm', root).addEventListener('submit', setup);
  $('#mfaConfirmForm', root).addEventListener('submit', confirm);
  $('#mfaDisableForm', root).addEventListener('submit', disable);
}

export function render() {
  if (!root) return;
  $('#mfaStatus', root).textContent = state.mfa
    ? 'MFA ativo: o código do aplicativo é pedido a cada login.'
    : 'MFA desligado. Recomendado se o radar estiver acessível pela internet.';
  $('#mfaSetupForm', root).classList.toggle('hidden', state.mfa);
  $('#mfaDisableForm', root).classList.toggle('hidden', !state.mfa);
  $('#pwCodeField', root).classList.toggle('hidden', !state.mfa);
  if (state.admin) loadSecurity();
}

const EVENT_LABELS = {
  login_ok: 'Login realizado',
  login_failed: 'Tentativa de login recusada',
  ip_blocked: 'IP bloqueado por excesso de tentativas',
  session_revoked: 'Sessão encerrada',
  other_sessions_revoked: 'Outras sessões encerradas',
  trusted_devices_revoked: 'Dispositivos confiáveis removidos',
  password_changed: 'Senha alterada',
  password_reset_env: 'Senha redefinida pelo .env',
  mfa_enabled: 'MFA ativado',
  mfa_disabled: 'MFA desativado',
  mfa_recovery_used: 'Código de recuperação usado',
};

/** A short, human label for a user-agent string. */
function describeDevice(agent = '') {
  const browser = /Edg\//.test(agent) ? 'Edge' : /Firefox\//.test(agent) ? 'Firefox' : /Chrome\//.test(agent) ? 'Chrome' : /Safari\//.test(agent) ? 'Safari' : 'Navegador';
  const system = /Android/.test(agent) ? 'Android' : /iPhone|iPad/.test(agent) ? 'iOS' : /Windows/.test(agent) ? 'Windows' : /Mac OS/.test(agent) ? 'macOS' : /Linux/.test(agent) ? 'Linux' : 'dispositivo';
  return `${browser} em ${system}`;
}

async function loadSecurity() {
  try {
    const data = await api('/api/auth/sessions');
    $('#deviceList', root).innerHTML = data.sessions
      .map(
        (item) => `
        <div class="row">
          <div class="row-head">
            <strong>${esc(describeDevice(item.user_agent))}</strong>
            ${item.current ? '<span class="badge badge-ok">Este dispositivo</span>' : `<button class="btn btn-sm btn-danger" type="button" data-revoke="${esc(item.id)}">Encerrar</button>`}
          </div>
          <span class="meta">IP ${esc(item.ip || '—')} · ativo ${esc(dateTime(item.last_seen_at))} · expira ${esc(dateTime(item.expires_at))}</span>
        </div>`,
      )
      .join('');
    $('#trustedInfo', root).textContent = data.trusted_devices
      ? `${data.trusted_devices} dispositivo(s) confiável(is) dispensam o código MFA.`
      : 'Nenhum dispositivo confiável.';
    $('#revokeTrusted', root).disabled = !data.trusted_devices;
    $('#eventList', root).innerHTML = data.events
      .slice(0, 12)
      .map((item) => `<li><span>${esc(EVENT_LABELS[item.type] || item.type)}</span><time>${esc(dateTime(item.at))} · ${esc(item.ip || '')}</time></li>`)
      .join('');
  } catch (error) {
    toast(error.message);
  }
}

async function onDeviceClick(event) {
  const button = event.target.closest('[data-revoke]');
  if (!button) return;
  try {
    await post('/api/auth/sessions/revoke', { id: button.dataset.revoke });
    toast('Sessão encerrada.');
    loadSecurity();
  } catch (error) {
    toast(error.message);
  }
}

async function testAlerts(event) {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const result = await post('/api/notifications/test');
    toast(`Teste enviado por: ${result.channels.join(' e ')}.`);
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
}

async function revokeOthers() {
  try {
    const result = await post('/api/auth/sessions/revoke-others');
    toast(`${result.revoked} sessão(ões) encerrada(s).`);
    loadSecurity();
  } catch (error) {
    toast(error.message);
  }
}

async function revokeTrusted() {
  try {
    await post('/api/auth/trusted-devices/revoke');
    toast('Dispositivos confiáveis removidos.');
    loadSecurity();
  } catch (error) {
    toast(error.message);
  }
}

async function changePassword(event) {
  event.preventDefault();
  try {
    await post('/api/auth/password', {
      current: $('#pwCurrent', root).value,
      new: $('#pwNew', root).value,
      code: $('#pwCode', root).value,
    });
    event.target.reset();
    toast('Senha alterada. Outros dispositivos foram desconectados.');
    loadSecurity();
  } catch (error) {
    toast(error.message);
  }
}

async function setup(event) {
  event.preventDefault();
  try {
    const result = await post('/api/auth/mfa/setup', { password: $('#mfaPassword', root).value });
    $('#qrImage', root).src = result.qr;
    $('#manualSecret', root).textContent = result.secret;
    $('#mfaQr', root).classList.remove('hidden');
    $('#mfaSetupForm', root).classList.add('hidden');
  } catch (error) {
    toast(error.message);
  }
}

async function confirm(event) {
  event.preventDefault();
  try {
    const result = await post('/api/auth/mfa/confirm', { code: $('#confirmCode', root).value });
    state.mfa = true;
    $('#mfaQr', root).classList.add('hidden');
    $('#recoveryCodes', root).textContent = result.recovery_codes.join('\n');
    $('#recovery', root).classList.remove('hidden');
    render();
    toast('MFA ativado. Guarde os códigos de recuperação.');
  } catch (error) {
    toast(error.message);
  }
}

async function disable(event) {
  event.preventDefault();
  if (!window.confirm('Desativar a verificação em duas etapas?')) return;
  try {
    await post('/api/auth/mfa/disable', { password: $('#disablePassword', root).value, code: $('#disableCode', root).value });
    state.mfa = false;
    $('#recovery', root).classList.add('hidden');
    render();
    toast('MFA desativado.');
  } catch (error) {
    toast(error.message);
  }
}
