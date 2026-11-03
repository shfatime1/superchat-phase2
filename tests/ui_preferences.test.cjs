// Dependency-free UI preference checks. No browser processes or network requests.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/ui.js'), 'utf8');

function fixture(saved, unavailable = false) {
  const elements = [], ids = {}, storage = new Map([['superchat.v1.saved', '{"history":"original"}']]);
  if (saved !== undefined) storage.set('superchat.ui.preferences', saved);
  class Element {
    constructor() { this.dataset = {}; this.attributes = {}; this.listeners = {}; this.textContent = ''; this.value = ''; this.active = false;
      this.classList = {toggle: (name, value) => { this.active = value; }, remove: () => {}}; elements.push(this); }
    setAttribute(name, value) { this.attributes[name] = value; }
    getAttribute(name) { return this.attributes[name] || ''; }
    addEventListener(type, callback) { this.listeners[type] = callback; }
    cloneNode() { return new Element(); }
    replaceChildren(...children) { this.children = children; }
    focus() {}
  }
  const get = id => ids[id] ||= new Element();
  ['theme-toggle', 'theme-toggle-sidebar', 'page-language', 'composer-domain', 'welcome-description',
   'message-input', 'sidebar', 'scrim', 'menu-button', 'conversation-list', 'messages'].forEach(get);
  get('composer-domain').parentElement = new Element();
  get('message-input').value = 'My unsent draft';
  const root = new Element(), meta = new Element(), themeIcon = new Element();
  const label = new Element(); label.dataset.themeLabel = '';
  const tabs = ['flights', 'shopping', 'cinema'].map(domain => { const el = new Element(); el.dataset.assistant = domain; return el; });
  const suggestions = tabs.map(() => {
    const el = new Element(), title = new Element(), icon = new Element();
    el.querySelector = selector => selector === 'strong' ? title : icon;
    return el;
  });
  const document = {
    documentElement: root, getElementById: get,
    querySelector: selector => selector.startsWith('meta') ? meta : selector === '.theme-icon' ? themeIcon : new Element(),
    querySelectorAll: selector => {
      if (selector === '[data-assistant]') return tabs;
      if (selector === '.suggestion') return suggestions;
      if (selector.startsWith('#')) return selector.split(',').map(s => get(s.slice(1)));
      const attribute = {'[data-i18n]': 'i18n', '[data-ui-text]': 'uiText', '[data-i18n-aria]': 'i18nAria', '[data-theme-label]': 'themeLabel'}[selector];
      return elements.filter(el => Object.hasOwn(el.dataset, attribute));
    }
  };
  const context = {document, window: {}, localStorage: {
    getItem: key => { if (unavailable) throw new Error('Storage disabled'); return storage.get(key); },
    setItem: (key, value) => { if (unavailable) throw new Error('Storage disabled'); storage.set(key, value); }
  }, fetch: () => { throw new Error('UI preferences must not call the backend'); }};
  vm.runInNewContext(source, context);
  return {ui: context.window.SuperChatUI, get, root, storage, Element, tabs};
}

test('theme and AZ/EN/RU changes preserve drafts, selection and saved conversations', () => {
  const f = fixture(), selected = new f.Element(); selected.checked = true;
  const action = new f.Element(); f.ui.setText(action, 'Compare selected');
  for (const [language, translated] of [['az', 'Seçilənləri müqayisə et'], ['ru', 'Сравнить выбранное'], ['en', 'Compare selected']]) {
    f.ui.setLanguage(language); assert.equal(action.textContent, translated); assert.equal(f.root.lang, language);
    f.ui.setTheme('light'); assert.equal(f.root.dataset.theme, 'light');
    f.ui.setTheme('dark'); assert.equal(f.root.dataset.theme, 'dark');
  }
  assert.equal(f.get('message-input').value, 'My unsent draft');
  assert.equal(selected.checked, true);
  assert.equal(f.storage.get('superchat.v1.saved'), '{"history":"original"}');
  assert.deepEqual([...f.storage.keys()].sort(), ['superchat.ui.preferences', 'superchat.v1.saved']);
});

test('preferences restore and assistant selection changes hints without submitting anything', () => {
  const f = fixture(JSON.stringify({theme: 'light', language: 'ru', assistant: 'shopping'}));
  assert.equal(f.root.dataset.theme, 'light'); assert.equal(f.get('message-input').placeholder, 'Что хотите найти?');
  f.tabs[2].listeners.click();
  assert.equal(f.get('message-input').placeholder, 'Что хотите посмотреть?');
  assert.equal(f.get('message-input').value, 'My unsent draft');
  assert.equal(JSON.parse(f.storage.get('superchat.ui.preferences')).assistant, 'cinema');
});

test('corrupt or unavailable storage and invalid choices do not prevent using the interface', () => {
  for (const f of [fixture('{bad json'), fixture(undefined, true)]) {
    f.ui.setLanguage('ru'); f.ui.setTheme('light'); f.ui.setLanguage('invalid'); f.ui.setTheme('invalid');
    assert.equal(f.root.lang, 'ru'); assert.equal(f.root.dataset.theme, 'light');
  }
});

test('every static interface translation key has AZ and RU text', () => {
  const f = fixture();
  const html = fs.readFileSync(path.join(__dirname, '../app/static/index.html'), 'utf8');
  const keys = [...html.matchAll(/data-i18n(?:-aria)?="([^"]+)"/g)].map(match => match[1]);
  for (const language of ['az', 'ru']) {
    f.ui.setLanguage(language);
    for (const key of keys) assert.notEqual(f.ui.translate(key), key, `${language}: ${key}`);
  }
});
