// In-memory practical UI checks. No browser process, microphone or network.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('app/static/bonuses.js', 'utf8');
function fixture(reply) {
  const ids = {}, sent = [], drafts = [], searches = [], tracks = [];
  let locked = false, now = 0, poll;
  const get = id => ids[id] ||= {value: '', hidden: true, dataset: {}, listeners: {},
    classList: {toggle() {}}, setAttribute() {}, removeAttribute() {},
    addEventListener(name, fn) { this.listeners[name] = fn; }, click() { this.listeners.click?.(); }};
  const composer = {get available() { return !locked; }, context: {id: 'chat-1'},
    lock(value) { locked = value; window.SuperChatBonuses?.setAvailability(true); },
    draft(...args) { assert.equal(locked, false); drafts.push(args); }, search(...args) { searches.push(args); }};
  class Recorder {
    static isTypeSupported(type) { return type.startsWith('audio/webm'); }
    constructor() { this.mimeType = 'audio/webm'; this.state = 'inactive'; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; this.ondataavailable({data: new Blob([new Uint8Array([26,69,223,163])], {type:'audio/webm'})}); this.onstop(); }
  }
  const analyser = {fftSize: 1024, level: .1, disconnect() {}, getFloatTimeDomainData(a) { a.fill(this.level); }};
  class Audio {
    state = 'running'; resume() { return Promise.resolve(); } close() { this.state='closed'; return Promise.resolve(); }
    createMediaStreamSource() { return {connect() {}, disconnect() {}}; } createAnalyser() { return analyser; }
  }
  const window = {SuperChatComposer: composer, SuperChatUI: {language:'en', translate:s=>s},
    AudioContext: Audio, MediaRecorder: Recorder, isSecureContext: true, addEventListener() {}};
  const context = {window, document: {getElementById: get, addEventListener() {}},
    Blob, ArrayBuffer, DataView, Float32Array, AbortController, DOMException,
    MediaRecorder: Recorder, performance: {now: () => now}, setTimeout, clearTimeout,
    setInterval(fn) { poll=fn; return 1; }, clearInterval() {},
    navigator: {mediaDevices: {getUserMedia: async () => ({getTracks: () => [{stop() { tracks.push(true); }}]})}},
    FileReader: class {readAsDataURL() { this.result='data:image/png;base64,test'; this.onload(); }},
    fetch: async (url, options) => { sent.push({url, options}); return {ok: true, json: async () => reply}; }};
  vm.runInNewContext(source, context);
  return {get, window, sent, drafts, searches, tracks, analyser,
    deny() { context.navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Denied', 'NotAllowedError'); }; },
    poll(t) { now=t; poll(); }};
}
const settle = () => new Promise(resolve => setImmediate(resolve));

test('image identification is reviewed before using existing search bridge', async () => {
  const f=fixture({identifiable:true, query:'wireless headphones', product_type:'headphones', attributes:['wireless'], confidence:.82,status:'ready'});
  const file=new Blob(['image'], {type:'image/png'});
  await f.get('image-upload').listeners.change({target:{files:[file],value:'photo'}});
  assert.equal(f.sent[0].url, '/api/shopping/visual');
  assert.equal(f.get('visual-review').hidden, false);
  assert.match(f.get('visual-confidence').textContent, /82%/);
  assert.equal(f.searches.length, 0);
  f.get('visual-query').value='headphones under $100';
  f.get('visual-search').listeners.click();
  assert.deepEqual(f.searches, [['headphones under $100','chat-1']]);
});

test('MediaRecorder and silence VAD transcribe into an editable draft without submitting', async () => {
  const f=fixture({speech_detected:true,text:'500$ dan ucuz notebooklar',language:'az'});
  await f.get('voice-button').listeners.click();
  f.poll(100); f.poll(300); f.analyser.level=0; f.poll(1900); await settle();
  assert.equal(f.sent[0].url, '/api/media/transcribe');
  assert.deepEqual(f.drafts, [['500$ dan ucuz notebooklar','chat-1','az']]);
  assert.equal(f.searches.length,0); assert.ok(f.tracks.length);
  assert.match(f.get('media-feedback').textContent,/Edit it/);
});

test('silence does not call Gemini and maximum recording time stops capture', async () => {
  const f=fixture({}); await f.get('voice-button').listeners.click();
  f.analyser.level=0; f.poll(7100); await settle();
  assert.equal(f.sent.length,0); assert.match(f.get('media-feedback').textContent,/No clear speech/);
  const vad=f.window.SuperChatMedia.createVAD(0);
  assert.equal(vad.update(.1,100),false); assert.equal(vad.update(.1,30000),true);
});

test('denied microphone permission releases the composer without sending audio', async () => {
  const f=fixture({}); f.deny();
  await f.get('voice-button').listeners.click();
  assert.equal(f.sent.length,0); assert.equal(f.window.SuperChatComposer.available,true);
  assert.match(f.get('media-feedback').textContent,/permission was denied/);
});
