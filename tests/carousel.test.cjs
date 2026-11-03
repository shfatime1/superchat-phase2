// Exercise the actual carousel function without launching a browser.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8');
const carouselCode = code.slice(code.indexOf('function carousel('), code.indexOf('function flightCard('));

function setup(total, reduced = false) {
  class Element {
    constructor(text) { this.children = []; this.textContent = text; this.dataset = {}; this.attrs = {}; this.listeners = {}; this.scrollLeft = 0; this.clientWidth = 700; this.classList = {add() {}}; }
    append(...children) { this.children.push(...children); }
    setAttribute(name, value) { this.attrs[name] = value; }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    get scrollWidth() { return this.children.length * 242; }
    scrollBy(options) { this.behavior = options.behavior; this.scrollLeft = Math.max(0, Math.min(this.scrollWidth - this.clientWidth, this.scrollLeft + options.left)); this.listeners.scroll?.(); }
  }
  const context = {busy: false, names: {shopping: 'Shopping'},
    node: (tag, cls, text) => new Element(text),
    button: (text, action) => { const e = new Element(text); e.click = action; return e; },
    window: {matchMedia: () => ({matches: reduced}), SuperChatUI: {translate: text => text, setText: (el, text) => { el.textContent = text; }}},
    requestAnimationFrame: callback => callback()};
  vm.runInNewContext(carouselCode, context);
  const rows = Array.from({length: total}, (_, id) => ({id})), grid = new Element();
  const result = context.carousel(grid, rows, row => { const e = new Element(); e.id = row.id; return e; }, 'shopping');
  return {grid, rows, previous: result.children[0].children[1], next: result.children[0].children[2]};
}

test('seven initial cards, all remaining results accessible by arrows, selections retained', () => {
  const f = setup(30);
  assert.equal(f.grid.children.length, 7); assert.equal(f.rows.length, 30);
  const first = f.grid.children[0]; first.checked = true;
  for (let i = 0; i < 20; i++) f.next.click();
  assert.equal(f.grid.children.length, 30);
  assert.deepEqual(f.grid.children.map(el => el.id), f.rows.map(row => row.id));
  assert.equal(f.grid.children[0], first); assert.equal(first.checked, true);
  assert.equal(f.next.disabled, true);
  f.previous.click(); assert.equal(f.grid.behavior, 'smooth');
  assert.equal(f.grid.children[29].attrs['aria-setsize'], '30');
});

test('swipe/scroll near the end loads the next batch without discarding results', () => {
  const f = setup(16);
  f.grid.scrollLeft = f.grid.scrollWidth - f.grid.clientWidth - 20;
  f.grid.listeners.scroll(); assert.equal(f.grid.children.length, 14);
  f.grid.scrollLeft = f.grid.scrollWidth - f.grid.clientWidth - 20;
  f.grid.listeners.scroll(); assert.equal(f.grid.children.length, 16);
});

test('small result sets and reduced motion preserve navigation boundaries', () => {
  const f = setup(2, true);
  assert.equal(f.grid.children.length, 2); assert.equal(f.previous.disabled, true);
  f.next.click(); assert.equal(f.grid.behavior, 'instant');
  assert.equal(f.next.disabled, true);
});
