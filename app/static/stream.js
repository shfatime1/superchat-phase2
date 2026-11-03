/* Incremental SSE over POST. Request IDs and cookies match the JSON chat API. */
"use strict";
window.SuperChatStream = async function(payload, signal, onEvent) {
  const response = await fetch("/api/chat/stream", {method: "POST", credentials: "same-origin",
    headers: {"Content-Type": "application/json", "Accept": "text/event-stream"}, body: JSON.stringify(payload), signal});
  if (!response.ok) { const error = new Error("Chat request failed"); error.status = response.status; throw error; }
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const {value, done} = await reader.read();
      buffer += decoder.decode(value, {stream: !done});
      buffer = buffer.replace(/\r\n/g, "\n");
      onEvent("heartbeat", {});
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
        let event = "message"; const data = [];
        frame.split("\n").forEach(line => {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
        });
        if (!data.length) continue;
        const body = JSON.parse(data.join("\n"));
        if (event === "error") { const error = new Error("Chat request failed"); error.status = body.status; error.retryAfter = body.retry_after; throw error; }
        if (event === "complete") return body;
        onEvent(event, body);
      }
      if (done) throw new Error("Stream ended before confirmation");
    }
  } finally { await reader.cancel().catch(() => {}); }
};
