const tg = window.Telegram?.WebApp;
const cfg = window.APP_CONFIG || {
  API_BASE_URL: '',
  AUTH_ENDPOINT: '/miniapp/auth',
  ENDPOINTS: {
    dashboard: '/miniapp/dashboard',
    extensionCode: '/miniapp/extension-code',
    activateKey: '/miniapp/activate-key',
  },
  DEMO_MODE: false,
};

const state = {
  token: null,
  me: null,
  plan: null,
  extension: null,
  dashboard: null,
  history: [],
  historyAnalytics: null,
  historyMode: 'list',
  page: 'plan',
};

const $ = (id) => document.getElementById(id);

const bottomNavState = { ticking: false };

const els = {
  toast: $('toast'),
  toastIcon: $('toastIcon'),
  toastTitle: $('toastTitle'),
  toastMessage: $('toastMessage'),

  avatar: $('avatar'),
  fullName: $('fullName'),
  username: $('username'),
  roleBadge: $('roleBadge'),
  accountStatus: $('accountStatus'),
  telegramId: $('telegramId'),
  createdAt: $('createdAt'),

  planTitle: $('planTitle'),
  planCode: $('planCode'),
  minutesLeft: $('minutesLeft'),
  minutesUsed: $('minutesUsed'),
  meetingsCount: $('meetingsCount'),
  subscriptionBadge: $('subscriptionBadge'),
  startsAt: $('startsAt'),
  endsAt: $('endsAt'),
  storageLimitLarge: $('storageLimitLarge'),
  featuresList: $('featuresList'),

  extensionCodeBox: $('extensionCodeBox'),
  extensionCode: $('extensionCode'),
  extensionExpires: $('extensionExpires'),
  extensionStatusBadge: $('extensionStatusBadge'),
  copyCodeBtn: $('copyCodeBtn'),

  genCodeBtn: $('genCodeBtn'),
  activateForm: $('activateForm'),
  activateInput: $('activateInput'),
  activateBtn: $('activateBtn'),
  refreshBtn: $('refreshBtn'),
  pageTitle: $('pageTitle'),
  historyList: $('historyList'),
  historySearchInput: $('historySearchInput'),
  historySearchBtn: $('historySearchBtn'),
  historyModeTabs: $('historyModeTabs'),
  historyPanelList: $('historyPanelList'),
  historyPanelAnalytics: $('historyPanelAnalytics'),
  historyAnalytics: $('historyAnalytics'),
};

const pageTitles = {
  profile: 'Профиль',
  plan: 'Тариф',
  history: 'История',
  extension: 'Расширение',
};

const demo = {
  auth: { access_token: 'demo_token' },
  dashboard: {
    me: {
      user: {
        id: '8c1635fe-123a-42cb-9c1e-a643bbc1c2d7',
        telegram_id: 720906456,
        username: 'Vladislav_Headliners',
        first_name: 'Vladislav',
        last_name: '',
        email: null,
        role: 'user',
        is_active: true,
        created_at: '2026-04-03T22:33:54.508542',
      },
    },
    plan: {
      code: 'extended',
      title: 'Расширенный',
      monthly_minutes: 2000,
      meeting_storage_limit: null,
      features: {
        transcription: { is_enabled: true, title: 'Транскрибация', description: 'Распознавание аудио и видео' },
        extension: { is_enabled: true, title: 'Расширение', description: 'Подключение браузерного расширения' },
        exports: { is_enabled: true, title: 'Экспорт', description: 'Выгрузки и результаты встреч' },
      },
    },
    subscription_status: 'active',
    starts_at: '2026-04-03T22:41:51',
    ends_at: '2026-05-03T22:41:51',
    usage_minutes: 0,
    remaining_minutes: 2000,
    meetings_count: 0,
  },
  history: {
    items: [
      {
        id: 'm1',
        title: 'Тестовая встреча',
        started_at: '2026-04-04T10:00:00',
        finished_at: '2026-04-04T10:24:00',
        duration_seconds: 1440,
        capture_mode: 'tab_mic',
        status: 'done',
        protocol_text: '🧾 ПРОТОКОЛ ВСТРЕЧИ\n\nКраткая сводка: обсудили запуск VocMind и ближайшие задачи.',
        transcript_text: 'ME: Проверили запись и договорились о следующем шаге.',
        exports: { pdf: true, docx: true }
      }
    ],
    features: {}
  },
  analyticsSummary: {
    enabled: true,
    totals: {
      meetings_total: 8,
      meetings_with_analytics: 8,
      total_duration_seconds: 14280,
      avg_duration_seconds: 1785,
      word_count: 6812,
      questions_count: 38,
      topics_count: 21,
      decisions_count: 12,
      action_items_count: 17,
      risks_count: 4,
    },
    timeline: [
      { label: '01.04', meetings: 1, duration_seconds: 1500, word_count: 680, questions_count: 4, decisions_count: 1, action_items_count: 2 },
      { label: '02.04', meetings: 2, duration_seconds: 2820, word_count: 1210, questions_count: 8, decisions_count: 2, action_items_count: 3 },
      { label: '03.04', meetings: 1, duration_seconds: 1740, word_count: 930, questions_count: 5, decisions_count: 2, action_items_count: 2 },
      { label: '04.04', meetings: 2, duration_seconds: 3180, word_count: 1660, questions_count: 10, decisions_count: 3, action_items_count: 4 },
      { label: '05.04', meetings: 2, duration_seconds: 5040, word_count: 2332, questions_count: 11, decisions_count: 4, action_items_count: 6 }
    ],
    top_keywords: [
      { keyword: 'продукт', count: 5 },
      { keyword: 'запуск', count: 4 },
      { keyword: 'отдел', count: 4 },
      { keyword: 'протокол', count: 3 },
      { keyword: 'аналитика', count: 3 },
      { keyword: 'команда', count: 3 }
    ],
    top_topics: [
      { topic: 'Запуск VocMind', count: 3 },
      { topic: 'Онбординг клиентов', count: 2 },
      { topic: 'Продажи и лиды', count: 2 },
      { topic: 'Roadmap продукта', count: 2 }
    ],
    talk_balance: { me_percent: 47.5, them_percent: 52.5 },
    recent_meetings: [
      { id: 'm1', title: 'Статус по продукту', started_at: '2026-04-05T16:10:00', duration_seconds: 2520, word_count: 1150, questions_count: 6, decisions_count: 2, action_items_count: 3, risks_count: 1 },
      { id: 'm2', title: 'Партнёрский созвон', started_at: '2026-04-05T12:40:00', duration_seconds: 1380, word_count: 620, questions_count: 3, decisions_count: 1, action_items_count: 2, risks_count: 0 }
    ]
  },
  extensionCode: {
    code: 'ukNOrE-GMB7u5W0qzPUT7FN6P5XsRY03tGcJF7HDi74',
    expires_at: '2026-04-04T23:15:00',
  },
};

let toastTimer = null;

function setText(el, value) {
  if (el) el.textContent = value;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function formatDate(v) {
  if (!v) return '—';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleString('ru-RU');
}

function formatHistoryStamp(v) {
  if (!v) return 'Запись';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return 'Запись';
  const date = d.toLocaleDateString('ru-RU');
  const time = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  return `Запись от ${date} в ${time}`;
}

function humanStorage(v) {
  return v == null ? '∞' : String(v);
}

function getInitial(name) {
  return (name || 'V').trim().charAt(0).toUpperCase() || 'V';
}

function formatRole(role) {
  const map = {
    user: 'Пользователь',
    admin: 'Админ',
    owner: 'Владелец',
    manager: 'Менеджер',
  };
  return map[String(role || '').toLowerCase()] || role || 'Пользователь';
}

function formatSubscriptionStatus(status) {
  const map = {
    active: 'Активна',
    trial: 'Пробная',
    expired: 'Истекла',
    canceled: 'Отменена',
    inactive: 'Неактивна',
    none: 'Без подписки',
  };
  return map[String(status || '').toLowerCase()] || (status ? String(status) : 'Без подписки');
}

function badgeToneByStatus(status) {
  const value = String(status || '').toLowerCase();
  if (['active', 'trial', 'ok', 'enabled', 'success'].includes(value)) return 'success';
  if (['expired', 'canceled', 'inactive', 'disabled', 'error'].includes(value)) return 'danger';
  if (['pending', 'warning'].includes(value)) return 'warning';
  return 'neutral';
}

function applyBadge(el, text, tone = 'neutral') {
  if (!el) return;
  el.textContent = text;
  el.className = `badge badge--${tone}`;
}

function setInitialLoading(on) {
  document.body.classList.toggle('is-loading', !!on);
  document.body.setAttribute('aria-busy', on ? 'true' : 'false');
}

function setButtonBusy(button, on, busyText) {
  if (!button) return;
  const label = button.querySelector('.btn__label, .icon-btn__label');

  if (on) {
    button.disabled = true;
    button.classList.add('is-busy');
    if (label && !button.dataset.originalLabel) {
      button.dataset.originalLabel = label.textContent;
    }
    if (label && busyText) {
      label.textContent = busyText;
    }
    return;
  }

  button.disabled = false;
  button.classList.remove('is-busy');
  if (label && button.dataset.originalLabel) {
    label.textContent = button.dataset.originalLabel;
  }
}

function showToast(message, type = 'success', title) {
  if (!els.toast) return;

  const titleMap = {
    success: 'Готово',
    error: 'Ошибка',
    info: 'Информация',
  };

  const iconMap = {
    success: `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="m5 12 5 5L20 7"/>
      </svg>
    `,
    error: `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 9v4"/>
        <path d="M12 17h.01"/>
        <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/>
      </svg>
    `,
    info: `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <path d="M12 16v-4"/>
        <path d="M12 8h.01"/>
      </svg>
    `,
  };

  els.toast.className = `toast toast--${type} show`;
  if (els.toastTitle) els.toastTitle.textContent = title || titleMap[type] || 'Готово';
  if (els.toastMessage) els.toastMessage.textContent = message;
  if (els.toastIcon) els.toastIcon.innerHTML = iconMap[type] || iconMap.info;

  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    els.toast?.classList.remove('show');
  }, 2600);
}

async function api(path, options = {}) {
  if (cfg.DEMO_MODE) {
    await delay(250);
    if (path === cfg.AUTH_ENDPOINT) return demo.auth;
    if (path === cfg.ENDPOINTS.dashboard) return demo.dashboard;
    if (path === cfg.ENDPOINTS.history) return demo.history;
    if (path === cfg.ENDPOINTS.historyAnalytics) return demo.analyticsSummary;
    if (path === cfg.ENDPOINTS.extensionCode) return demo.extensionCode;
    if (path === cfg.ENDPOINTS.activateKey) {
      return {
        ok: true,
        message: 'Ключ активирован',
        plan: demo.dashboard.plan,
        starts_at: demo.dashboard.starts_at,
        ends_at: demo.dashboard.ends_at,
      };
    }
    throw new Error(`Unknown demo endpoint: ${path}`);
  }

  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }

  const response = await fetch(`${cfg.API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  const text = await response.text();
  let data = {};

  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }

  if (!response.ok) {
    throw new Error(data.detail || data.message || `HTTP ${response.status}`);
  }

  return data;
}

async function authMiniApp() {
  if (cfg.DEMO_MODE) {
    state.token = demo.auth.access_token;
    return;
  }

  const initData = tg?.initData || '';
  if (!initData) {
    throw new Error('Mini App открыт не из Telegram или initData пустой');
  }

  const data = await api(cfg.AUTH_ENDPOINT, {
    method: 'POST',
    body: JSON.stringify({ init_data: initData }),
  });

  if (!data?.access_token) {
    throw new Error('Бэкенд не вернул access_token');
  }

  state.token = data.access_token;
}

function renderProfile() {
  const u = state.me?.user || {};
  const fullName = [u.first_name, u.last_name].filter(Boolean).join(' ').trim() || 'Без имени';

  setText(els.avatar, getInitial(fullName));
  setText(els.fullName, fullName);
  setText(els.username, u.username ? `@${u.username}` : 'Username не указан');
  setText(els.telegramId, u.telegram_id != null ? String(u.telegram_id) : 'Не указан');
  setText(els.createdAt, formatDate(u.created_at));

  applyBadge(els.roleBadge, formatRole(u.role), u.role === 'admin' ? 'warning' : 'neutral');
  applyBadge(els.accountStatus, u.is_active ? 'Активен' : 'Неактивен', u.is_active ? 'success' : 'danger');
}

function getFeatureTitle(key, value) {
  return value?.title || key;
}

function getFeatureDescription(key, value) {
  if (value?.description) return value.description;
  if (value?.feature_value != null && value.feature_value !== '') {
    return `Значение: ${String(value.feature_value)}`;
  }
  return 'Функция активна';
}

function renderPlan() {
  const p = state.plan || {};
  const d = state.dashboard || {};
  const features = p.features || {};
  const hiddenFeatureKeys = new Set(['transcription', 'tasks_and_decisions']);
  const items = Object.entries(features).filter(([key, value]) => value && value.is_enabled && !hiddenFeatureKeys.has(key));

  setText(els.planTitle, p.title || 'Нет тарифа');
  setText(els.planCode, p.code || 'Нет кода');
  setText(els.startsAt, formatDate(d.starts_at));
  setText(els.endsAt, formatDate(d.ends_at));
  setText(els.minutesLeft, d.remaining_minutes ?? '—');
  setText(els.minutesUsed, d.usage_minutes ?? '—');
  setText(els.meetingsCount, d.meetings_count ?? '—');
  setText(els.storageLimitLarge, humanStorage(p.meeting_storage_limit));
  applyBadge(els.subscriptionBadge, formatSubscriptionStatus(d.subscription_status), badgeToneByStatus(d.subscription_status));

  if (!els.featuresList) return;

  if (!items.length) {
    els.featuresList.className = 'features-list empty-state';
    els.featuresList.innerHTML = `
      <div class="empty-state__title">Функции пока не подключены</div>
      <div class="empty-state__text">Когда в тарифе появятся активные модули, они отобразятся здесь.</div>
    `;
    return;
  }

  els.featuresList.className = 'features-list features-list--compact';
  els.featuresList.innerHTML = items
    .map(([key, value]) => `
      <div class="feature feature--compact">
        <div class="feature__title">${escapeHtml(getFeatureTitle(key, value))}</div>
      </div>
    `)
    .join('');
}

function updateCopyButton() {
  const hasCode = !!state.extension?.code;
  if (els.copyCodeBtn) {
    els.copyCodeBtn.disabled = !hasCode;
  }
}

function renderExtension() {
  const e = state.extension;

  if (!e?.code) {
    if (els.extensionCodeBox) {
      els.extensionCodeBox.classList.add('code-box--empty');
    }
    setText(els.extensionCode, 'Код ещё не создан');
    setText(els.extensionExpires, 'Сгенерируй код, чтобы подключить расширение');
    applyBadge(els.extensionStatusBadge, 'Не создан', 'neutral');
    updateCopyButton();
    return;
  }

  if (els.extensionCodeBox) {
    els.extensionCodeBox.classList.remove('code-box--empty');
  }
  setText(els.extensionCode, e.code);
  setText(els.extensionExpires, e.expires_at ? `Действует до ${formatDate(e.expires_at)}` : 'Без срока');
  applyBadge(els.extensionStatusBadge, 'Готов', 'success');
  updateCopyButton();
}


function currentFeatures() {
  return state.plan?.features || {};
}

function featureEnabled(code) {
  return !!currentFeatures()?.[code]?.is_enabled;
}

function formatDuration(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds) || 0));
  const mm = Math.floor(s / 60);
  const ss = s % 60;
  return `${mm}:${String(ss).padStart(2, '0')}`;
}


function formatMinutesShort(seconds) {
  const value = Math.max(0, Math.round((Number(seconds) || 0) / 60));
  return `${value} мин`;
}

function formatNumber(value) {
  return new Intl.NumberFormat('ru-RU').format(Number(value) || 0);
}

function formatPercent(value) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return `${Number(value).toFixed(1)}%`;
}

function setHistoryMode(mode) {
  const analyticsEnabled = featureEnabled('meeting_analytics');
  const nextMode = analyticsEnabled && mode === 'analytics' ? 'analytics' : 'list';
  state.historyMode = nextMode;

  if (els.historyPanelList) {
    const active = nextMode === 'list';
    els.historyPanelList.hidden = !active;
    els.historyPanelList.classList.toggle('active', active);
  }
  if (els.historyPanelAnalytics) {
    const active = nextMode === 'analytics' && analyticsEnabled;
    els.historyPanelAnalytics.hidden = !active;
    els.historyPanelAnalytics.classList.toggle('active', active);
  }
  document.querySelectorAll('[data-history-mode]').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-history-mode') === nextMode);
  });
}

function renderHistoryModeControls() {
  const analyticsEnabled = featureEnabled('meeting_analytics');
  if (els.historyModeTabs) {
    els.historyModeTabs.hidden = !analyticsEnabled;
  }
  if (!analyticsEnabled && state.historyMode !== 'list') {
    state.historyMode = 'list';
  }
  setHistoryMode(state.historyMode || 'list');
}

function renderAnalytics() {
  if (!els.historyAnalytics) return;
  const analyticsEnabled = featureEnabled('meeting_analytics');

  if (!analyticsEnabled) {
    els.historyAnalytics.className = 'analytics-view empty-state';
    els.historyAnalytics.innerHTML = `
      <div class="empty-state__title">Аналитика недоступна</div>
      <div class="empty-state__text">Эта вкладка открывается на тарифах Расширенный и Админ.</div>
    `;
    renderHistoryModeControls();
    return;
  }

  const data = state.historyAnalytics || {};
  const totals = data.totals || {};
  const timeline = Array.isArray(data.timeline) ? data.timeline : [];
  const topKeywords = Array.isArray(data.top_keywords) ? data.top_keywords : [];
  const topTopics = Array.isArray(data.top_topics) ? data.top_topics : [];
  const recentMeetings = Array.isArray(data.recent_meetings) ? data.recent_meetings : [];
  const talkBalance = data.talk_balance || {};

  if (!totals.meetings_total) {
    els.historyAnalytics.className = 'analytics-view empty-state';
    els.historyAnalytics.innerHTML = `
      <div class="empty-state__title">Пока нет данных для аналитики</div>
      <div class="empty-state__text">Запиши несколько встреч на тарифе с аналитикой — здесь появятся графики, ключевые темы и сводка.</div>
    `;
    renderHistoryModeControls();
    return;
  }

  const maxMinutes = Math.max(...timeline.map((item) => Math.max(1, Math.round((Number(item.duration_seconds) || 0) / 60))), 1);
  const barsHtml = timeline.map((item) => {
    const minutes = Math.max(1, Math.round((Number(item.duration_seconds) || 0) / 60));
    const height = Math.max(12, Math.round((minutes / maxMinutes) * 132));
    return `
      <div class="analytics-bar">
        <div class="analytics-bar__meta">${escapeHtml(String(item.meetings || 0))}</div>
        <div class="analytics-bar__value" style="height:${height}px"></div>
        <div class="analytics-bar__label">${escapeHtml(item.label || '—')}</div>
      </div>
    `;
  }).join('');

  const keywordsHtml = topKeywords.length
    ? topKeywords.map((item) => `<span class="chip chip--accent">${escapeHtml(item.keyword)} · ${escapeHtml(String(item.count))}</span>`).join('')
    : '<span class="muted">Пока нет выраженных ключевых слов.</span>';

  const topicsHtml = topTopics.length
    ? topTopics.map((item) => `<span class="chip chip--ghost">${escapeHtml(item.topic)} · ${escapeHtml(String(item.count))}</span>`).join('')
    : '<span class="muted">Темы появятся после накопления встреч.</span>';

  const meetingsHtml = recentMeetings.length
    ? recentMeetings.map((item) => `
        <div class="analytics-meeting">
          <div class="analytics-meeting__top">
            <div>
              <div class="analytics-meeting__title">${escapeHtml(item.title || 'Встреча')}</div>
              <div class="analytics-meeting__meta">${escapeHtml(formatHistoryStamp(item.started_at))} · ${escapeHtml(formatDuration(item.duration_seconds))}</div>
            </div>
            <span class="badge badge--neutral">${escapeHtml(formatNumber(item.word_count || 0))} слов</span>
          </div>
          <div class="analytics-metrics">
            <span class="analytics-metric">Вопросы: ${escapeHtml(formatNumber(item.questions_count || 0))}</span>
            <span class="analytics-metric">Решения: ${escapeHtml(formatNumber(item.decisions_count || 0))}</span>
            <span class="analytics-metric">Задачи: ${escapeHtml(formatNumber(item.action_items_count || 0))}</span>
            <span class="analytics-metric">Риски: ${escapeHtml(formatNumber(item.risks_count || 0))}</span>
          </div>
        </div>
      `).join('')
    : '<div class="muted">Недавние встречи пока не найдены.</div>';

  els.historyAnalytics.className = 'analytics-view';
  els.historyAnalytics.innerHTML = `
    <div class="analytics-grid analytics-grid--compact analytics-grid--summary">
      <div class="analytics-stat">
        <div class="analytics-stat__label">Всего встреч</div>
        <div class="analytics-stat__value">${escapeHtml(formatNumber(totals.meetings_total || 0))}</div>
        <div class="analytics-stat__sub">С аналитикой: ${escapeHtml(formatNumber(totals.meetings_with_analytics || 0))}</div>
      </div>
      <div class="analytics-stat">
        <div class="analytics-stat__label">Общее время встреч</div>
        <div class="analytics-stat__value">${escapeHtml(formatMinutesShort(totals.total_duration_seconds || 0))}</div>
        <div class="analytics-stat__sub">Средняя встреча: ${escapeHtml(formatDuration(totals.avg_duration_seconds || 0))}</div>
      </div>
      <div class="analytics-stat">
        <div class="analytics-stat__label">Вопросы и решения</div>
        <div class="analytics-stat__value">${escapeHtml(formatNumber(totals.questions_count || 0))}</div>
        <div class="analytics-stat__sub">Решения: ${escapeHtml(formatNumber(totals.decisions_count || 0))} · Задачи: ${escapeHtml(formatNumber(totals.action_items_count || 0))}</div>
      </div>
      <div class="analytics-stat">
        <div class="analytics-stat__label">Наполненность</div>
        <div class="analytics-stat__value">${escapeHtml(formatNumber(totals.word_count || 0))}</div>
        <div class="analytics-stat__sub">Темы: ${escapeHtml(formatNumber(totals.topics_count || 0))} · Риски: ${escapeHtml(formatNumber(totals.risks_count || 0))}</div>
      </div>
    </div>

    <div class="analytics-stack analytics-stack--wide">
      <div class="analytics-card analytics-card--chart">
        <h3 class="analytics-card__title">Динамика по встречам</h3>
        <div class="analytics-chart">
          <div class="analytics-bars">${barsHtml || '<div class="muted">Недостаточно данных для графика.</div>'}</div>
          <div class="muted analytics-card__hint">Высота столбца показывает суммарную длительность встреч по дням, число сверху — сколько встреч было в этот день.</div>
        </div>
      </div>

      <div class="analytics-card balance-card">
        <h3 class="analytics-card__title">Баланс разговора</h3>
        <div class="balance-row">
          <div class="balance-row__head"><span>Вы</span><span>${escapeHtml(formatPercent(talkBalance.me_percent))}</span></div>
          <div class="balance-track"><div class="balance-track__fill" style="width:${Math.max(0, Math.min(100, Number(talkBalance.me_percent) || 0))}%"></div></div>
        </div>
        <div class="balance-row">
          <div class="balance-row__head"><span>Собеседники</span><span>${escapeHtml(formatPercent(talkBalance.them_percent))}</span></div>
          <div class="balance-track"><div class="balance-track__fill" style="width:${Math.max(0, Math.min(100, Number(talkBalance.them_percent) || 0))}%"></div></div>
        </div>
      </div>
    </div>

    <div class="analytics-stack analytics-stack--chips">
      <div class="analytics-card">
        <h3 class="analytics-card__title">Частые ключевые слова</h3>
        <div class="chips-wrap">${keywordsHtml}</div>
      </div>

      <div class="analytics-card">
        <h3 class="analytics-card__title">Частые темы встреч</h3>
        <div class="chips-wrap">${topicsHtml}</div>
      </div>
    </div>

    <div class="analytics-card analytics-card--meetings">
      <h3 class="analytics-card__title">Последние встречи</h3>
      <div class="analytics-meetings">${meetingsHtml}</div>
    </div>
  `;

  renderHistoryModeControls();
}

function renderHistory() {
  if (!els.historyList) return;
  const items = Array.isArray(state.history) ? state.history : [];
  const searchEnabled = featureEnabled('meeting_search');

  renderHistoryModeControls();

  if (els.historySearchInput) {
    els.historySearchInput.disabled = !searchEnabled;
    els.historySearchInput.placeholder = searchEnabled ? 'Поиск по встречам' : 'Поиск доступен с тарифа Профессиональный';
  }
  if (els.historySearchBtn) els.historySearchBtn.disabled = !searchEnabled;

  if (!items.length) {
    els.historyList.className = 'history-list empty-state';
    els.historyList.innerHTML = `
      <div class="empty-state__title">История пока пуста</div>
      <div class="empty-state__text">После первой записи встреча появится здесь.</div>
    `;
    return;
  }

  els.historyList.className = 'history-list';
  els.historyList.innerHTML = items.map((item) => {
    const exportActions = [
      item.exports?.pdf ? `<button class="btn" data-export="${escapeHtml(item.id)}:pdf" type="button"><span class="btn__label">PDF</span></button>` : '',
      item.exports?.docx ? `<button class="btn" data-export="${escapeHtml(item.id)}:docx" type="button"><span class="btn__label">DOCX</span></button>` : '',
      `<button class="btn" data-delete-meeting="${escapeHtml(item.id)}" type="button"><span class="btn__label">Удалить</span></button>`,
    ].join('');
    return `
      <details class="history-entry">
        <summary class="history-entry__summary">
          <div>
            <div class="history-entry__title">${escapeHtml(formatHistoryStamp(item.started_at))}</div>
            <div class="history-entry__meta">${escapeHtml(formatDuration(item.duration_seconds))} · ${escapeHtml(item.capture_mode === 'tab_mic' ? 'вкладка + мик' : 'микрофон')} · ${escapeHtml(formatSubscriptionStatus(item.status || 'done'))}</div>
          </div>
          <span class="history-entry__chevron" aria-hidden="true">⌄</span>
        </summary>
        <div class="history-entry__body">
          <div class="history-entry__block">
            <div class="history-entry__label">${escapeHtml(item.title || 'Встреча')}</div>
            <div class="history-entry__text">${escapeHtml(item.protocol_text || 'Протокол пока недоступен')}</div>
          </div>
          <div class="actions-row history-entry__actions">
            ${exportActions}
          </div>
        </div>
      </details>
    `;
  }).join('');
}

async function loadHistory(query = '') {
  try {
    let path = cfg.ENDPOINTS.history;
    if (query) path += `?q=${encodeURIComponent(query)}`;
    const data = await api(path, { method: 'GET' });
    state.history = data.items || [];
    renderHistory();
  } catch (error) {
    console.error(error);
    showToast(error.message || 'Не удалось загрузить историю', 'error');
  }
}

async function loadHistoryAnalytics() {
  if (!featureEnabled('meeting_analytics')) {
    state.historyAnalytics = null;
    renderAnalytics();
    return;
  }

  try {
    const data = await api(cfg.ENDPOINTS.historyAnalytics, { method: 'GET' });
    state.historyAnalytics = data || null;
    renderAnalytics();
  } catch (error) {
    console.error(error);
    state.historyAnalytics = null;
    renderAnalytics();
    showToast(error.message || 'Не удалось загрузить аналитику встреч', 'error');
  }
}

async function deleteMeeting(id) {
  try {
    await api(`${cfg.ENDPOINTS.history}/${id}`, { method: 'DELETE', headers: {} });
    state.history = (state.history || []).filter((item) => item.id !== id);
    renderHistory();
    await loadAll(false);
  } catch (error) {
    showToast(error.message || 'Не удалось удалить встречу', 'error');
  }
}


async function downloadMeetingExport(id, fmt) {
  try {
    const headers = {};
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    const response = await fetch(`${cfg.API_BASE_URL}${cfg.ENDPOINTS.history}/${encodeURIComponent(id)}/export/${encodeURIComponent(fmt)}`, { headers });
    if (!response.ok) {
      const text = await response.text();
      let data = {};
      try { data = text ? JSON.parse(text) : {}; } catch {}
      throw new Error(data.detail || `HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `vocmind_meeting.${fmt}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    showToast(error.message || 'Не удалось скачать экспорт', 'error');
  }
}

function bindHistoryActions() {
  els.historyList?.addEventListener('click', async (event) => {
    const exportBtn = event.target.closest('[data-export]');
    const deleteBtn = event.target.closest('[data-delete-meeting]');
    if (exportBtn) {
      const raw = exportBtn.getAttribute('data-export') || '';
      const [id, fmt] = raw.split(':');
      await downloadMeetingExport(id, fmt);
      return;
    }
    if (deleteBtn) {
      await deleteMeeting(deleteBtn.getAttribute('data-delete-meeting'));
    }
  });
}

function applyDashboard(dashboard) {
  state.dashboard = dashboard || null;
  state.me = dashboard?.me || null;
  state.plan = dashboard?.plan || null;

  renderProfile();
  renderPlan();
  renderHistory();
  renderAnalytics();
}

async function loadAll(showSuccessToast = true, sourceButton = null) {
  if (sourceButton) {
    setButtonBusy(sourceButton, true, 'Обновляем');
  }

  try {
    if (!state.token) {
      await authMiniApp();
    }

    const dashboard = await api(cfg.ENDPOINTS.dashboard, { method: 'GET' });
    applyDashboard(dashboard);
    await loadHistory(els.historySearchInput?.value || "");
    await loadHistoryAnalytics();

    if (showSuccessToast) {
      showToast('Данные кабинета обновлены', 'success');
    }
  } catch (error) {
    console.error(error);
    showToast(error.message || 'Не удалось обновить данные', 'error');
  } finally {
    if (sourceButton) {
      setButtonBusy(sourceButton, false);
    }
    setInitialLoading(false);
  }
}

async function generateExtensionCode() {
  setButtonBusy(els.genCodeBtn, true, 'Генерируем');

  try {
    state.extension = await api(cfg.ENDPOINTS.extensionCode, {
      method: 'POST',
      body: '{}',
    });
    renderExtension();
    showToast('Код расширения создан', 'success');
    try { tg?.HapticFeedback?.notificationOccurred?.('success'); } catch {}
  } catch (error) {
    console.error(error);
    showToast(`Не удалось получить код: ${error.message}`, 'error');
    try { tg?.HapticFeedback?.notificationOccurred?.('error'); } catch {}
  } finally {
    setButtonBusy(els.genCodeBtn, false);
  }
}

async function copyExtensionCode() {
  const code = state.extension?.code;
  if (!code) {
    showToast('Сначала сгенерируй код', 'info');
    return;
  }

  try {
    await navigator.clipboard.writeText(code);
    showToast('Код скопирован в буфер', 'success');
    try { tg?.HapticFeedback?.notificationOccurred?.('success'); } catch {}
  } catch (error) {
    console.error(error);
    showToast('Не удалось скопировать код', 'error');
  }
}

async function activateKey(event) {
  event.preventDefault();

  const key = els.activateInput?.value?.trim() || '';
  if (!key) {
    showToast('Введи ключ активации', 'error');
    return;
  }

  setButtonBusy(els.activateBtn, true, 'Активируем');

  try {
    const res = await api(cfg.ENDPOINTS.activateKey, {
      method: 'POST',
      body: JSON.stringify({ key }),
    });

    showToast(res.message || 'Ключ активирован', 'success');
    if (els.activateInput) els.activateInput.value = '';
    await loadAll(false);
  } catch (error) {
    console.error(error);
    showToast(`Ошибка активации: ${error.message}`, 'error');
  } finally {
    setButtonBusy(els.activateBtn, false);
  }
}


function updateBottomNavPosition() {
  const nav = document.querySelector('.bottom-nav');
  const slot = document.getElementById('bottomNavSlot');
  if (!nav || !slot) return;

  const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
  const slotRect = slot.getBoundingClientRect();
  const navBottomGap = 10;
  const shouldDock = slotRect.bottom <= viewportHeight - navBottomGap;

  nav.classList.toggle('is-docked', shouldDock);
}

function requestBottomNavPositionUpdate() {

  if (bottomNavState.ticking) return;
  bottomNavState.ticking = true;
  window.requestAnimationFrame(() => {
    bottomNavState.ticking = false;
    updateBottomNavPosition();
  });
}

function bindBottomNavPosition() {
  requestBottomNavPositionUpdate();
  window.addEventListener('scroll', requestBottomNavPositionUpdate, { passive: true });
  window.addEventListener('resize', requestBottomNavPositionUpdate);
}

function switchPage(page) {
  state.page = page;

  document.querySelectorAll('.pages > .page').forEach((el) => {
    const isActive = el.id === `page-${page}`;
    el.classList.toggle('active', isActive);
    el.hidden = !isActive;
  });

  document.querySelectorAll('.nav-btn').forEach((el) => {
    el.classList.toggle('active', el.dataset.page === page);
  });

  setText(els.pageTitle, pageTitles[page] || 'VocMind');
  requestBottomNavPositionUpdate();
}

function bindNavigation() {
  document.querySelectorAll('.nav-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      switchPage(btn.dataset.page);
      try { tg?.HapticFeedback?.selectionChanged?.(); } catch {}
    });
  });
}

function bindEvents() {
  els.refreshBtn?.addEventListener('click', () => loadAll(true, els.refreshBtn));
  els.genCodeBtn?.addEventListener('click', generateExtensionCode);
  els.copyCodeBtn?.addEventListener('click', copyExtensionCode);
  els.activateForm?.addEventListener('submit', activateKey);
  els.historySearchBtn?.addEventListener('click', () => loadHistory(els.historySearchInput?.value || ""));
  els.historySearchInput?.addEventListener('keydown', (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      loadHistory(els.historySearchInput?.value || "");
    }
  });
  els.historyModeTabs?.addEventListener('click', (event) => {
    const btn = event.target.closest('[data-history-mode]');
    if (!btn) return;
    setHistoryMode(btn.getAttribute('data-history-mode') || 'list');
    try { tg?.HapticFeedback?.selectionChanged?.(); } catch {}
  });
  bindHistoryActions();
}

function setupTelegram() {
  if (!tg) return;

  try { tg.ready(); } catch {}
  try { tg.expand(); } catch {}
  try { tg.setHeaderColor?.('#0b0f14'); } catch {}
  try { tg.setBackgroundColor?.('#0b0f14'); } catch {}
}

window.addEventListener('error', (event) => {
  console.error('Miniapp error:', event.error || event.message);
});

(async function init() {
  setupTelegram();
  bindNavigation();
  bindEvents();
  bindBottomNavPosition();
  switchPage('plan');
  renderExtension();
  await loadAll(false);
})();
