export function duration(ms) {
  const s = Math.max(0, Math.floor(ms / 1000))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`
}

export const WARN_MS = 15 * 60 * 1000
export const CRIT_MS = 60 * 60 * 1000

export function level(ms) {
  return ms >= CRIT_MS ? "crit" : ms >= WARN_MS ? "warn" : "ok"
}

export function sessionsFrom(response) {
  let body = response
  for (let i = 0; i < 3 && body && !Array.isArray(body); i++) body = body.data ?? body.items
  return Array.isArray(body) ? body : []
}

export function running(session) {
  const t = session.time ?? {}
  return Boolean(t.busy) && (!t.idle || t.busy > t.idle)
}

export function shellRows({ shells = [], owners = {}, now, limit = 8 }) {
  return shells
    .filter((s) => s.status === "running" && owners[s.metadata?.sessionID] !== undefined)
    .map((s) => {
      const start = s.time?.started ?? now
      const line = String(s.command ?? "").split("\n", 1)[0].trim()
      return {
        id: s.id,
        command: line.length > 60 ? line.slice(0, 59) + "…" : line,
        owner: owners[s.metadata.sessionID],
        elapsed: duration(now - start),
        level: level(now - start),
        start,
      }
    })
    .sort((a, b) => a.start - b.start)
    .slice(0, limit)
}

export function rows({ sessions = [], parentID, models = [], now, limit = 8 }) {
  const name = (model) => {
    const found = models.find((m) => m.providerID === model?.providerID &&
      (m.id === model?.id || m.modelID === model?.id))
    return found?.name ?? model?.id ?? "?"
  }
  return sessions
    .filter((s) => s.parentID === parentID)
    .map((s) => {
      const active = running(s)
      const start = s.time?.created ?? now
      const end = active ? now : (s.time?.idle ?? s.time?.updated ?? now)
      return {
        id: s.id,
        active,
        title: s.title ?? s.id,
        agent: s.agent ?? "agent",
        model: name(s.model),
        effort: s.model?.variant ?? "default",
        elapsed: duration(end - start),
        level: level(end - start),
        start,
      }
    })
    .filter((r) => r.active)
    .sort((a, b) => b.start - a.start)
    .slice(0, limit)
}
