const $ = (id) => document.getElementById(id);

const state = {
  entryToken: '',
  enterTimer: null,
  localWhitelist: false,
};

function initialMessage() {
  const params = new URLSearchParams(window.location.search);
  return params.get('session') === 'expired' ? '会话已失效，请重新登录' : '等待输入邮箱';
}

function setAuthStatus(text, authenticated = false) {
  const element = $('auth-status');
  element.textContent = text;
  element.className = `status ${authenticated ? 'connected' : 'disconnected'}`;
}

function setResult(text, kind = 'idle') {
  const element = $('auth-result');
  element.textContent = text;
  element.className = `result-line ${kind}`;
}

function setEnterButton(enabled, text = '进入邮箱') {
  const button = $('enter-mailbox-btn');
  button.disabled = !enabled;
  button.textContent = text;
  button.classList.toggle('inactive-btn', !enabled);
}

function setLoggedInActions(authenticated) {
  $('logout-btn').classList.toggle('hidden', !authenticated);
  $('login-btn').classList.toggle('hidden', authenticated);
  $('query-account-btn').classList.toggle('hidden', authenticated);
}

function clearEntryState() {
  state.entryToken = '';
  if (state.enterTimer) {
    window.clearTimeout(state.enterTimer);
    state.enterTimer = null;
  }
  setEnterButton(false);
}

function credentialsPayload() {
  return {
    email: $('login-email').value.trim(),
    password: $('login-password').value,
  };
}

function displayName(data = {}) {
  return data.access_all ? '本机白名单' : (data.email || data.username || '');
}

function applyWhitelistMode(enabled) {
  state.localWhitelist = Boolean(enabled);
  $('login-email').disabled = state.localWhitelist;
  $('login-password').disabled = state.localWhitelist;
  $('query-account-btn').textContent = state.localWhitelist ? '查看邮箱' : '查询账号';
  $('login-btn').textContent = state.localWhitelist ? '本机直接登录' : '登录';
  $('service-state').textContent = state.localWhitelist ? '本机白名单' : '服务已连接';
}

function validateCredentials() {
  if (state.localWhitelist) return true;
  const payload = credentialsPayload();
  if (!payload.email || !payload.password) {
    setResult('请输入邮箱和密码', 'err');
    return false;
  }
  return true;
}

function renderAccount(data = {}) {
  $('summary-email').textContent = data.access_all
    ? `全部邮箱 (${data.account_count ?? 0})`
    : (data.email || data.username || '-');
  $('summary-source').textContent = data.access_all ? '本机白名单' : (data.source_file || '-');
  $('summary-sessions').textContent = data.active_session_count ?? '-';
}

function setButtonBusy(button, busy, busyText) {
  if (busy) {
    button.dataset.label = button.textContent;
    button.textContent = busyText;
  } else if (button.dataset.label) {
    button.textContent = button.dataset.label;
  }
  button.disabled = busy;
  button.classList.toggle('running', busy);
}

async function readJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.message || data.error || `请求失败: ${response.status}`);
    error.data = data;
    throw error;
  }
  return data;
}

async function postJson(path, payload = {}) {
  const response = await fetch(path, {
    method: 'POST',
    credentials: 'same-origin',
    cache: 'no-store',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return readJson(response);
}

async function queryAccount() {
  if (!validateCredentials()) return;
  const button = $('query-account-btn');
  clearEntryState();
  setButtonBusy(button, true, '查询中');
  setResult('正在查询账号', 'busy');
  try {
    const data = await postJson('/api/auth/query', credentialsPayload());
    applyWhitelistMode(data.local_whitelist);
    renderAccount(data);
    setResult(data.access_all ? `已发现 ${data.account_count || 0} 个邮箱` : '账号可用', 'ok');
  } catch (error) {
    renderAccount();
    setResult(error.message || '查询失败', 'err');
  } finally {
    setButtonBusy(button, false, '查询中');
  }
}

async function login(event) {
  event?.preventDefault();
  if (!validateCredentials()) return;
  const button = $('login-btn');
  clearEntryState();
  setButtonBusy(button, true, '登录中');
  setResult('正在建立邮箱会话', 'busy');
  try {
    const data = await postJson('/api/auth/login', credentialsPayload());
    if (!data.entry_token) throw new Error('登录响应缺少入口令牌');
    state.entryToken = data.entry_token;
    applyWhitelistMode(data.local_whitelist);
    renderAccount(data);
    $('login-password').value = '';
    setAuthStatus(`已登录: ${displayName(data)}`, true);
    setLoggedInActions(true);
    setEnterButton(false, '3秒后可进入');
    setResult(
      data.access_all ? `登录成功，可访问 ${data.account_count || 0} 个邮箱` : '登录成功，会话已建立',
      'ok',
    );
    state.enterTimer = window.setTimeout(() => {
      state.enterTimer = null;
      if (!state.entryToken) return;
      setEnterButton(true);
      setResult('登录成功，可以进入邮箱', 'ok');
    }, 3000);
  } catch (error) {
    setAuthStatus('未登录', false);
    setLoggedInActions(false);
    renderAccount();
    setResult(error.message || '登录失败', 'err');
    clearEntryState();
  } finally {
    setButtonBusy(button, false, '登录中');
  }
}

function enterMailbox() {
  if (!state.entryToken) {
    setResult('当前会话没有可用的入口令牌', 'err');
    return;
  }
  const url = new URL('/mailbox', window.location.origin);
  url.searchParams.set('entry', state.entryToken);
  window.location.assign(`${url.pathname}${url.search}`);
}

async function logout() {
  const button = $('logout-btn');
  setButtonBusy(button, true, '退出中');
  try {
    await postJson('/api/auth/logout');
  } catch {
    // Local state is cleared even if the server session already expired.
  }
  clearEntryState();
  renderAccount();
  setLoggedInActions(false);
  setAuthStatus('未登录', false);
  setResult('已退出', 'idle');
  setButtonBusy(button, false, '退出中');
}

async function bootstrap() {
  $('service-state').textContent = '正在连接服务';
  setResult(initialMessage(), 'idle');
  try {
    const response = await fetch('/api/auth/me', {
      credentials: 'same-origin',
      cache: 'no-store',
    });
    const data = await readJson(response);
    applyWhitelistMode(data.local_whitelist);
    if (!data.authenticated) {
      setAuthStatus('未登录', false);
      setLoggedInActions(false);
      setEnterButton(false);
      return;
    }
    state.entryToken = data.entry_token || '';
    if (!data.access_all) $('login-email').value = data.email || '';
    renderAccount(data);
    setAuthStatus(`已登录: ${displayName(data)}`, true);
    setLoggedInActions(true);
    setEnterButton(Boolean(state.entryToken));
    setResult('会话已恢复', 'ok');
  } catch {
    setAuthStatus('未登录', false);
    setLoggedInActions(false);
    setEnterButton(false);
  }
}

$('login-form').addEventListener('submit', login);
$('query-account-btn').addEventListener('click', queryAccount);
$('enter-mailbox-btn').addEventListener('click', enterMailbox);
$('logout-btn').addEventListener('click', logout);

bootstrap();
