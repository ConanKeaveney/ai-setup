import assert from "node:assert/strict"
import { test } from "node:test"
import { mkdtemp, mkdir, writeFile, rm, readFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { createHash } from "node:crypto"
import { payload, render, spans } from "./core.mjs"

const selected = { providerID: "fixture", modelID: "test" }
const models = [{ providerID: "fixture", id: "test", name: "Fixture Model", limit: { context: 1000000 } }]
const message = { type: "assistant", model: { providerID: "fixture", id: "test" },
  tokens: { input: 100000, output: 20000, cache: { read: 280000, write: 20000 } } }
const fixture = { selected, models, messages: [message], cwd: "/nonexistent/synthetic-statusline" }

test("negative controls: absent, invalid, compacted and other-model usage stays unknown", () => {
  for (const messages of [[], [{ ...message, tokens: {} }],
    [{ ...message, tokens: { ...message.tokens, input: -1 } }],
    [message, { type: "compaction" }],
    [{ ...message, model: { providerID: "other", id: "test" } }]]) {
    assert.equal(payload({ ...fixture, messages }).context_window, undefined)
  }
  assert.equal(payload({ ...fixture, models: [] }).context_window, undefined)
  assert.equal(payload(fixture).rate_limits, undefined)
})

test("context is latest request usage, including cache, not session totals", () => {
  const data = payload({ ...fixture, messages: [message, message] })
  assert.equal(data.model.display_name, "Fixture Model")
  assert.equal(data.context_window.used_percentage, 42)
  assert.equal(data.context_window.context_window_size, 1000000)
})

test("ANSI colours, bold and reset become safe text spans", () => {
  assert.deepEqual(spans("\x1b[1;31mwarning\x1b[0m ok"), [
    { text: "warning", bold: true, color: "#ef4444" }, { text: " ok" },
  ])
  assert.equal(spans("bad\x1b]title\x07")[0].text.includes("\x1b"), false)
})

test("real Claude renderer receives OpenCode data without exporting Claude limits", async (t) => {
  const home = await mkdtemp(join(tmpdir(), "statusline-test-"))
  t.after(() => rm(home, { recursive: true, force: true }))
  const options = { env: { OPENCODE_STATUSLINE_USAGE_HOME: home, CODEX_HOME: join(home, ".codex") } }
  const line = (await render(payload(fixture), options)).map((p) => p.text).join("")
  assert.match(line, /Fixture Model/)
  assert.match(line, /synthetic-statusline/)
  assert.match(line, /ctx 42%/)
  assert.match(line, /\/1M/)
  assert.match(line, /limits unknown/)
  assert.match(line, /Claude Code limits unknown/)
  assert.match(line, /Codex limits unknown/)
  const unknown = (await render(payload({ ...fixture, messages: [] }), options)).map((p) => p.text).join("")
  assert.match(unknown, /ctx unknown/)
  assert.doesNotMatch(unknown, /ctx 0%/)
  await mkdir(join(home, ".claude/state"), { recursive: true })
  const path = join(home, ".claude/state/rate-limits.json")
  const capture = JSON.stringify({ captured_at: Date.now() / 1000,
    rate_limits: { seven_day: { used_percentage: 73, resets_at: Date.now() / 1000 + 3600 } } })
  await writeFile(path, capture)
  const fresh = (await render(payload(fixture), options)).map((p) => p.text).join("")
  assert.match(fresh, /Claude Code 7d 73% used/)
  assert.doesNotMatch(fresh, /5h/)
  assert.match(fresh, /Codex limits unknown/)
  assert.equal(await readFile(path, "utf8"), capture)
  await mkdir(join(home, ".codex"))
  await mkdir(join(home, ".cache/opencode-statusline"), { recursive: true })
  await writeFile(join(home, ".codex/auth.json"), JSON.stringify({ tokens: {
    account_id: "fixture-account", access_token: "fixture-token",
  } }))
  const identity = createHash("sha256").update("fixture-account").digest("hex")
  await writeFile(join(home, `.cache/opencode-statusline/codex-${identity}.json`), JSON.stringify({
    captured_at: Date.now() / 1000, checked_at: Date.now() / 1000,
    rate_limits: { primary_window: { used_percent: 24, limit_window_seconds: 604800,
      reset_at: Date.now() / 1000 + 3600 }, secondary_window: null },
  }))
  const both = (await render(payload(fixture), options)).map((p) => p.text).join("")
  assert.match(both, /Claude Code 7d 73% used, week 99% through \(resets in 1h00m\)/)
  assert.match(both, /Codex 7d 24% used, week 99% through \(resets in 1h00m\)/)
  assert.doesNotMatch(both, /limits unknown/)
})
