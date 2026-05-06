/**
 * Overwolf API wrapper.
 * 브라우저 개발 시: mock 데이터로 stub
 * Overwolf 환경:   실제 SDK 호출
 */

const IS_OW = typeof overwolf !== 'undefined';

// ── 이벤트 버스 (브라우저 개발용) ───────────────────────────
const _listeners = {};
function _emit(event, data) {
  (_listeners[event] || []).forEach(cb => cb(data));
}
function _on(event, cb) {
  if (!_listeners[event]) _listeners[event] = [];
  _listeners[event].push(cb);
  return () => { _listeners[event] = _listeners[event].filter(f => f !== cb); };
}

// ── 브라우저 mock: 챔피언 자동감지 시뮬 ──────────────────────
if (!IS_OW) {
  setTimeout(() => _emit('championChanged', { name: 'Riven', id: 'riven' }), 800);
}

// ── 윈도우 관리 ──────────────────────────────────────────────
export const Windows = {
  toggle(windowName = 'overlay') {
    if (!IS_OW) return;
    overwolf.windows.getWindowState(windowName, ({ window_state }) => {
      if (window_state === 'normal' || window_state === 'maximized') {
        overwolf.windows.hide(windowName, () => {});
      } else {
        overwolf.windows.restore(windowName, () => {});
      }
    });
  },

  open(windowName = 'overlay') {
    if (!IS_OW) return;
    overwolf.windows.obtainDeclaredWindow(windowName, ({ window }) => {
      overwolf.windows.restore(window.id, () => {});
    });
  },

  close(windowName = 'overlay') {
    if (!IS_OW) return;
    overwolf.windows.close(windowName, () => {});
  },
};

// ── 게임 이벤트 (챔피언 감지) ────────────────────────────────
export const GameEvents = {
  /** cb: ({ name, id }) */
  onChampionChanged(cb) {
    if (IS_OW) {
      overwolf.games.events.onInfoUpdates2.addListener(info => {
        const champ = info?.info?.me?.champion;
        if (champ) cb({ name: champ, id: champ.toLowerCase() });
      });
      // 현재 챔피언 즉시 조회
      overwolf.games.events.getInfo(info => {
        const champ = info?.res?.me?.champion;
        if (champ) cb({ name: champ, id: champ.toLowerCase() });
      });
    } else {
      return _on('championChanged', cb);
    }
  },

  setRequiredFeatures(features = ['live_client_data', 'me', 'champion']) {
    if (!IS_OW) return;
    overwolf.games.events.setRequiredFeatures(features, status => {
      console.log('[OW] setRequiredFeatures:', status);
    });
  },
};

// ── 키 입력 추적 ─────────────────────────────────────────────
export const Input = {
  /**
   * cb: ({ key: string, timeMs: number })
   * 브라우저: document keydown 이벤트 사용
   * Overwolf: overwolf.games.inputTracking
   */
  onKeyDown(cb) {
    if (IS_OW) {
      overwolf.games.inputTracking.onKeyDown.addListener(event => {
        cb({ key: event.key, timeMs: performance.now() });
      });
    } else {
      const handler = e => {
        if (e.repeat) return;
        cb({ key: e.key.toUpperCase(), timeMs: performance.now() });
      };
      document.addEventListener('keydown', handler);
      return () => document.removeEventListener('keydown', handler);
    }
  },
};

// ── 핫키 ─────────────────────────────────────────────────────
export const Hotkeys = {
  onToggleOverlay(cb) {
    if (IS_OW) {
      overwolf.settings.hotkeys.onPressed.addListener(event => {
        if (event.name === 'toggle_overlay') cb();
      });
    } else {
      const handler = e => { if (e.key === 'F10') cb(); };
      document.addEventListener('keydown', handler);
      return () => document.removeEventListener('keydown', handler);
    }
  },
  onPrevCombo(cb) {
    if (IS_OW) {
      overwolf.settings.hotkeys.onPressed.addListener(e => { if (e.name === 'prev_combo') cb(); });
    } else {
      const h = e => { if (e.key === 'F7') cb(); };
      document.addEventListener('keydown', h);
      return () => document.removeEventListener('keydown', h);
    }
  },
  onNextCombo(cb) {
    if (IS_OW) {
      overwolf.settings.hotkeys.onPressed.addListener(e => { if (e.name === 'next_combo') cb(); });
    } else {
      const h = e => { if (e.key === 'F8') cb(); };
      document.addEventListener('keydown', h);
      return () => document.removeEventListener('keydown', h);
    }
  },
};

// ── combogg 웹 API ───────────────────────────────────────────
const API_BASE = 'https://combogg-web.vercel.app';

export const ComboggAPI = {
  async fetchCombos(characterSlug) {
    try {
      const res = await fetch(`${API_BASE}/api/combos?game=lol&character=${characterSlug}&status=published&limit=20`);
      if (!res.ok) throw new Error(res.status);
      const data = await res.json();
      return data.combos || data.items || data || [];
    } catch (e) {
      console.warn('[ComboggAPI] fetchCombos failed, using mock', e);
      return MOCK_COMBOS;
    }
  },
};

// ── Mock 콤보 (API 실패 시 폴백) ─────────────────────────────
const MOCK_COMBOS = [
  {
    id: 'mock-01',
    title: '기본 풀콤보',
    difficulty: 'hard',
    inputs: [
      { t: 0,    key: 'Q',  label: 'Q 1타' },
      { t: 380,  key: 'AA', label: '평타' },
      { t: 700,  key: 'Q',  label: 'Q 2타' },
      { t: 950,  key: 'AA', label: '평캔' },
      { t: 1200, key: 'E',  label: 'E' },
      { t: 1700, key: 'R',  label: 'R 1타' },
      { t: 2100, key: 'AA', label: '평타' },
      { t: 2400, key: 'Q',  label: 'Q 3타' },
    ],
    steps: [
      { label: '1단', start: 0,    end: 1050 },
      { label: '2단', start: 1050, end: 1700 },
      { label: '3단', start: 1700, end: 2900 },
    ],
  },
  {
    id: 'mock-02',
    title: '짧은 견제 콤보',
    difficulty: 'easy',
    inputs: [
      { t: 0,   key: 'Q',  label: 'Q' },
      { t: 350, key: 'AA', label: '평타' },
      { t: 650, key: 'E',  label: 'E' },
    ],
    steps: [
      { label: '전부', start: 0, end: 900 },
    ],
  },
];

export default { Windows, GameEvents, Input, Hotkeys, ComboggAPI };
