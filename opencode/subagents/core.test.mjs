import { test } from "node:test"
import assert from "node:assert/strict"
import { duration, level, rows, sessionsFrom, shellRows } from "./core.mjs"

const models = [{ providerID: "claude-agent", id: "opus", name: "Opus 5.5" }]

test("shows model name, effort and running time for running children only", () => {
  const now = 1_000_000
  const out = rows({
    now, models, parentID: "p",
    sessions: [
      { id: "a", parentID: "p", agent: "general", title: "Audit", model: { providerID: "claude-agent", id: "opus", variant: "high" },
        time: { created: now - 125_000, busy: now - 1000, idle: now - 5000 } },
      { id: "b", parentID: "p", agent: "explore", title: "Done", model: { providerID: "x", id: "y" },
        time: { created: now - 60_000, busy: now - 50_000, idle: now - 30_000 } },
      { id: "c", parentID: "other", title: "Not mine", time: { created: now } },
    ],
  })
  assert.deepEqual(out.map((r) => [r.id, r.active, r.model, r.effort, r.elapsed]), [
    ["a", true, "Opus 5.5", "high", "2m 05s"],
  ])
})

test("reads the session array from any client response shape", () => {
  const list = [{ id: "a" }]
  assert.deepEqual(sessionsFrom(list), list)
  assert.deepEqual(sessionsFrom({ data: list }), list)
  assert.deepEqual(sessionsFrom({ data: { data: list } }), list)
  assert.deepEqual(sessionsFrom({ data: { items: list } }), list)
  assert.deepEqual(sessionsFrom(undefined), [])
})

test("lists running shells of this session and its subagents, oldest first", () => {
  const now = 10_000_000
  const out = shellRows({
    now,
    owners: { p: "", c: "general: Audit" },
    shells: [
      { id: "s1", status: "running", command: "sleep 60\necho done", metadata: { sessionID: "c" }, time: { started: now - 20 * 60_000 } },
      { id: "s2", status: "running", command: "cargo test", metadata: { sessionID: "p" }, time: { started: now - 5000 } },
      { id: "s3", status: "exited", command: "ls", metadata: { sessionID: "p" }, time: { started: now - 1000 } },
      { id: "s4", status: "running", command: "other", metadata: { sessionID: "x" }, time: { started: now } },
    ],
  })
  assert.deepEqual(out.map((r) => [r.id, r.command, r.owner, r.elapsed, r.level]), [
    ["s1", "sleep 60", "general: Audit", "20m 00s", "warn"],
    ["s2", "cargo test", "", "5s", "ok"],
  ])
})

test("formats long durations in hours", () => {
  assert.equal(duration(3_725_000), "1h 02m")
})

test("colours time yellow from 15 minutes and red from 60 minutes", () => {
  assert.equal(level(15 * 60_000 - 1), "ok")
  assert.equal(level(15 * 60_000), "warn")
  assert.equal(level(60 * 60_000 - 1), "warn")
  assert.equal(level(60 * 60_000), "crit")
})
