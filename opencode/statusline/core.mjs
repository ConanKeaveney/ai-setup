import { execFile } from "node:child_process"
import { fileURLToPath } from "node:url"

export function payload({ selected, models = [], messages = [], cwd }) {
  const model = models.find((m) => m.providerID === selected?.providerID &&
    (m.id === selected?.modelID || m.modelID === selected?.modelID))
  const data = {
    model: { display_name: model?.name ?? selected?.modelID ?? "OpenCode" },
    workspace: { current_dir: cwd },
  }
  for (const message of [...messages].reverse()) {
    if (message.type === "compaction") break
    if (message.type !== "assistant" || !message.tokens) continue
    if (message.model?.providerID !== selected?.providerID ||
        message.model?.id !== selected?.modelID) break
    const t = message.tokens
    const values = [t.input, t.output, t.cache?.read, t.cache?.write]
    if (values.every((n) => typeof n === "number" && Number.isFinite(n) && n >= 0) &&
        Number.isFinite(model?.limit?.context) && model.limit.context > 0) {
      data.context_window = {
        used_percentage: values.reduce((a, b) => a + b, 0) / model.limit.context * 100,
        context_window_size: model.limit.context,
      }
    }
    break
  }
  return data
}

const colors = { 31: "#ef4444", 32: "#22c55e", 33: "#eab308", 35: "#d946ef", 36: "#06b6d4" }

export function spans(line) {
  const result = []
  let style = {}
  let end = 0
  for (const match of line.matchAll(/\x1b\[([\d;]*)m/g)) {
    if (match.index > end) result.push({ text: line.slice(end, match.index), ...style })
    for (const code of (match[1] || "0").split(";").map(Number)) {
      if (code === 0) style = {}
      else if (code === 1) style.bold = true
      else if (code === 2) style.dim = true
      else if (colors[code]) style.color = colors[code]
    }
    end = match.index + match[0].length
  }
  if (end < line.length) result.push({ text: line.slice(end), ...style })
  return result.map((part) => ({ ...part, text: part.text.replace(/[\x00-\x1f\x7f-\x9f]/g, " ") }))
}

export function render(data, { env = {} } = {}) {
  return new Promise((resolve, reject) => {
    const child = execFile("python3", [fileURLToPath(new URL("./bridge.py", import.meta.url))],
      { timeout: 4000, maxBuffer: 65536, env: { ...process.env, ...env, PYTHONDONTWRITEBYTECODE: "1" } },
      (error, stdout) => {
        if (error) return reject(error)
        try {
          const value = JSON.parse(stdout)
          if (typeof value.line !== "string") throw new Error("Missing status line")
          resolve(spans(value.line))
        } catch (error) { reject(error) }
      })
    child.stdin.on("error", () => {})
    child.stdin.end(JSON.stringify(data))
  })
}
