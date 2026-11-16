import { Plugin } from "@opencode/plugin/tui"
import { createEffect, createMemo, createSignal, For, onCleanup } from "solid-js"
import { payload, render } from "./core.mjs"

export default Plugin.define({
  id: "personal.claude-statusline",
  setup(context) {
    function Status(props: { sessionID?: string }) {
      const [parts, setParts] = createSignal([{ text: "status loading…" }])
      const input = createMemo(() => {
        const session = props.sessionID ? context.data.session.get(props.sessionID) : undefined
        const location = session?.location ?? context.location ?? context.data.location.default()
        return JSON.stringify(payload({
          selected: context.ui.model.current(),
          models: context.data.location.model.list(location),
          messages: props.sessionID ? context.data.session.message.list(props.sessionID) : [],
          cwd: location.directory ?? process.cwd(),
        }))
      })
      let closed = false
      let running = false
      let pending = false
      async function refresh() {
        if (running) { pending = true; return }
        running = true
        const snapshot = input()
        try {
          const next = await render(JSON.parse(snapshot))
          if (!closed && snapshot === input()) setParts(next)
        } catch {
          if (!closed) setParts([{ text: "status unavailable | ctx unknown | limits unknown" }])
        } finally {
          running = false
          if (pending && !closed) { pending = false; void refresh() }
        }
      }
      createEffect(() => {
        input()
        const timer = setTimeout(() => void refresh(), 150)
        onCleanup(() => clearTimeout(timer))
      })
      const timer = setInterval(() => void refresh(), 10000)
      onCleanup(() => { closed = true; clearInterval(timer) })
      return <text wrapMode="word" flexShrink={1}>
        <For each={parts()}>{(part: any) =>
          <span style={{ fg: part.color ?? (part.dim ? context.theme.text.muted : context.theme.text.base) }}>
            {part.bold ? <b>{part.text}</b> : part.text}
          </span>
        }</For>
      </text>
    }
    return context.ui.slot({
      replace: "prompt.footer.status",
      render: (props) => <Status sessionID={props.sessionID} />,
    })
  },
})
