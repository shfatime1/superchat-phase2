const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '../app/static/stream.js'), 'utf8');

function setup(text) {
  const bytes = new TextEncoder().encode(text), events = [];
  const context = {window: {}, TextDecoder, fetch: async (url, options) => {
    assert.equal(url, '/api/chat/stream'); assert.equal(options.credentials, 'same-origin');
    assert.equal(JSON.parse(options.body).request_id, 'stable-request-id');
    return {ok: true, body: new ReadableStream({start(controller) {
      // One-byte chunks deliberately split both UTF-8 characters and SSE frames.
      for (const byte of bytes) controller.enqueue(Uint8Array.of(byte)); controller.close();
    }})};
  }};
  vm.runInNewContext(code, context);
  return {run: () => context.window.SuperChatStream({request_id: 'stable-request-id'}, null, (event, body) => {
    if (event !== 'heartbeat') events.push([event, body]);
  }), events};
}

test('incremental UTF-8/CRLF SSE frames deliver progress and text before final answer', async () => {
  const f = setup('event: progress\r\ndata: {"step":"routing"}\r\n\r\n: keep-alive\r\n\r\nevent: text\r\ndata: {"delta":"Uçuşlar — Рейсы"}\r\n\r\nevent: complete\r\ndata: {"message":"done"}\r\n\r\n');
  assert.equal((await f.run()).message, 'done');
  assert.equal(f.events[0][0], 'progress'); assert.equal(f.events[1][1].delta, 'Uçuşlar — Рейсы');
});

test('rate-limit errors and incomplete streams remain failures, never confirmations', async () => {
  await assert.rejects(setup('event: error\ndata: {"status":429,"retry_after":30}\n\n').run(), error => error.status === 429 && error.retryAfter === 30);
  await assert.rejects(setup('event: text\ndata: {"delta":"partial"}\n\n').run(), /before confirmation/);
});
