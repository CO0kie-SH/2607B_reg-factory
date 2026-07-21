const $ = (id) => document.getElementById(id);

const state = {
  email: '',
  accounts: [],
  selectedAccount: null,
  recipients: [],
  folders: [],
  selectedFolder: null,
};

function setResult(text, kind = 'idle') {
  const element = $('mailbox-result');
  element.textContent = text;
  element.className = `result-line ${kind}`;
}

async function readJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.message || data.error || `请求失败: ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return data;
}

async function apiGet(path) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    cache: 'no-store',
  });
  if (response.status === 401) {
    window.location.replace('/?session=expired');
    throw new Error('会话已失效');
  }
  return readJson(response);
}

function folderLabel(folder) {
    return folder.path || folder.display_name || folder.id || '未命名文件夹';
}

function renderAccounts() {
  const list = $('account-list');
  list.replaceChildren();
  $('account-count').textContent = String(state.accounts.length);

  for (const account of state.accounts) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'account-item secondary-btn';
    button.textContent = account.email;
    if (state.selectedAccount?.email === account.email) button.classList.add('active');
    button.addEventListener('click', () => selectAccount(account));
    list.appendChild(button);
  }

  if (!state.accounts.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = '没有可用邮箱';
    list.appendChild(empty);
  }
}

function renderRecipients() {
  const list = $('recipient-list');
  list.replaceChildren();
  $('recipient-count').textContent = String(state.recipients.length);

  for (const recipient of state.recipients) {
    const item = document.createElement('div');
    item.className = 'recipient-item';

    const copy = document.createElement('div');
    copy.className = 'recipient-copy';
    const address = document.createElement('span');
    address.textContent = recipient.address || '-';
    address.title = recipient.address || '';
    const meta = document.createElement('small');
    const observed = `${recipient.message_count || 0} 封`;
    meta.textContent = recipient.is_primary ? `主邮箱 · ${observed}` : observed;
    copy.append(address, meta);

    const link = document.createElement('a');
    link.className = 'recipient-api-link';
    link.href = recipient.latest_subject_url || '#';
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = '标题 API';
    link.title = `获取 ${recipient.address || '该地址'} 的最新邮件标题`;
    item.append(copy, link);
    list.appendChild(item);
  }

  if (!state.recipients.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state recipient-empty';
    empty.textContent = '没有发现收件地址';
    list.appendChild(empty);
  }
}

function chooseInitialFolder(folders) {
  const preferred = folders.find((folder) => /(^|\/)(inbox|收件箱)$/i.test(folderLabel(folder)));
  return preferred || folders[0] || null;
}

function renderFolders() {
  const list = $('folder-list');
  list.replaceChildren();
  $('folder-count').textContent = String(state.folders.length);

  for (const folder of state.folders) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'folder-item secondary-btn';
    if (state.selectedFolder?.id === folder.id) button.classList.add('active');

    const name = document.createElement('span');
    name.textContent = folderLabel(folder);
    const count = document.createElement('small');
    count.textContent = String(folder.unread_item_count ?? 0);
    button.append(name, count);
    button.addEventListener('click', () => selectFolder(folder));
    list.appendChild(button);
  }

  if (!state.folders.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = '没有可用文件夹';
    list.appendChild(empty);
  }
}

function senderText(message) {
  const sender = message.from?.emailAddress || message.sender?.emailAddress || {};
  return sender.name || sender.address || '-';
}

function recipientText(message) {
  const addresses = (message.toRecipients || [])
    .map((recipient) => recipient.emailAddress?.address?.trim())
    .filter(Boolean);
  return [...new Set(addresses)].join(', ') || '-';
}

function formatTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function renderMessages(messages) {
  const body = $('message-list');
  body.replaceChildren();
  if (!messages.length) {
    const row = document.createElement('tr');
    row.className = 'empty-row';
    const cell = document.createElement('td');
    cell.colSpan = 4;
    cell.textContent = '该文件夹暂无邮件';
    row.appendChild(cell);
    body.appendChild(row);
    return;
  }

  for (const message of messages) {
    const row = document.createElement('tr');
    if (!message.isRead) row.classList.add('unread');

    const subject = document.createElement('td');
    subject.dataset.label = '主题';
    subject.textContent = message.subject || '(无主题)';

    const sender = document.createElement('td');
    sender.dataset.label = '发件人';
    sender.textContent = senderText(message);

    const recipient = document.createElement('td');
    recipient.dataset.label = '收件人';
    recipient.textContent = recipientText(message);

    const received = document.createElement('td');
    received.dataset.label = '接收时间';
    received.textContent = formatTime(message.receivedDateTime);

    row.append(subject, sender, recipient, received);
    body.appendChild(row);
  }
}

async function loadMessages() {
  const folder = state.selectedFolder;
  const account = state.selectedAccount;
  if (!folder || !account) {
    renderMessages([]);
    return;
  }

  setResult('正在读取邮件', 'busy');
  $('selected-folder').textContent = folderLabel(folder);
  try {
    const params = new URLSearchParams({
      email: account.email,
      folder: folder.id,
      top: $('message-limit').value,
    });
    const data = await apiGet(`/api/messages?${params}`);
    renderMessages(data.messages || []);
    setResult(`已读取 ${data.count || 0} 封邮件`, 'ok');
  } catch (error) {
    renderMessages([]);
    setResult(error.message || '邮件读取失败', 'err');
  }
}

async function selectFolder(folder) {
  state.selectedFolder = folder;
  renderFolders();
  await loadMessages();
}

async function selectAccount(account) {
  if (!account) return;
  state.selectedAccount = account;
  state.email = account.email;
  state.recipients = [];
  state.folders = [];
  state.selectedFolder = null;
  $('mailbox-account').textContent = account.email;
  renderAccounts();
  renderRecipients();
  renderFolders();
  renderMessages([]);
  await loadRecipients();
  await loadFolders();
}

async function loadAccounts(preferredEmail = '') {
  setResult('正在读取邮箱列表', 'busy');
  try {
    const data = await apiGet('/api/accounts');
    state.accounts = data.accounts || [];
    renderAccounts();
    const preferred = state.accounts.find(
      (account) => account.email.toLowerCase() === preferredEmail.toLowerCase(),
    );
    await selectAccount(preferred || state.accounts[0] || null);
  } catch (error) {
    state.accounts = [];
    state.selectedAccount = null;
    state.recipients = [];
    renderAccounts();
    renderRecipients();
    setResult(error.message || '邮箱列表读取失败', 'err');
  }
}

async function loadRecipients() {
  const account = state.selectedAccount;
  if (!account) {
    state.recipients = [];
    renderRecipients();
    return;
  }

  setResult('正在读取收件地址', 'busy');
  try {
    const email = encodeURIComponent(account.email);
    const data = await apiGet(`/api/mailboxes/${email}/recipients`);
    state.recipients = data.recipients || [];
    renderRecipients();
  } catch (error) {
    state.recipients = [];
    renderRecipients();
    setResult(error.message || '收件地址读取失败', 'err');
  }
}

async function loadFolders() {
  if (!state.selectedAccount) {
    setResult('请选择邮箱', 'idle');
    return;
  }
  setResult('正在读取文件夹', 'busy');
  try {
    const params = new URLSearchParams({ email: state.selectedAccount.email });
    const data = await apiGet(`/api/folders?${params}`);
    state.folders = data.folders || [];
    state.selectedFolder = chooseInitialFolder(state.folders);
    renderFolders();
    await loadMessages();
  } catch (error) {
    state.folders = [];
    state.selectedFolder = null;
    renderFolders();
    renderMessages([]);
    setResult(error.message || '文件夹读取失败', 'err');
  }
}

async function refreshMailbox() {
  await loadRecipients();
  await loadFolders();
}

async function logout() {
  try {
    await fetch('/api/auth/logout', {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { 'content-type': 'application/json' },
      body: '{}',
    });
  } finally {
    window.location.replace('/');
  }
}

async function bootstrap() {
  try {
    const data = await apiGet('/api/auth/me');
    if (!data.authenticated) {
      window.location.replace('/?session=expired');
      return;
    }
    state.email = data.email || '';
    $('mailbox-account').textContent = data.access_all ? '全部邮箱' : state.email;
    $('mailbox-status').textContent = '已登录';
    await loadAccounts(state.email);
  } catch (error) {
    if (error.status !== 401) setResult(error.message || '初始化失败', 'err');
  }
}

$('refresh-btn').addEventListener('click', refreshMailbox);
$('mailbox-logout-btn').addEventListener('click', logout);
$('message-limit').addEventListener('change', loadMessages);

bootstrap();
