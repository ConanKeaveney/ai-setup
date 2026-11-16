import { Plugin } from "@opencode/plugin/tui"
import { Rpc } from "@opencode/plugin/rpc"
import { createEffect, createMemo, createSignal, For, onCleanup, Show } from "solid-js"
import { rows, sessionsFrom, shellRows } from "./core.mjs"

const Goal = Rpc.define({ id: "opencode.goal", methods: { get: {} } })

const timeColor = { warn: "#eab308", crit: "#ef4444" }

export default Plugin.define({
  id: "personal.subagents-sidebar",
  setup(context) {
    function Subagents(props: { sessionID?: string }) {
      const [now, setNow] = createSignal(Date.now())
      const [children, setChildren] = createSignal<any[]>([])
      const [error, setError] = createSignal<string>()
      const [shells, setShells] = createSignal<any[]>([])
      const [goal, setGoal] = createSignal<{ objective: string; status: string }>()
      let closed = false
      async function refresh() {
        const parentID = props.sessionID
        if (!parentID) return setChildren([])
        try {
          const response = await (context.client as any).session.list({ parentID, limit: 20, order: "desc" })
          if (!closed && parentID === props.sessionID) { setChildren(sessionsFrom(response)); setError(undefined) }
        } catch (e) {
          if (!closed) setError(String((e as Error)?.message ?? e).slice(0, 80))
        }
        try {
          const session = context.data.session.get(parentID)
          const location = session?.location ?? context.location ?? context.data.location.default()
          const response = await (context.client as any).shell.list({ location })
          if (!closed && parentID === props.sessionID) setShells(sessionsFrom(response))
        } catch {
          if (!closed) setShells([])
        }
        try {
          const current = await context.client.rpc(Goal).get({ sessionID: parentID }) as any
          if (!closed && parentID === props.sessionID) setGoal(current?.objective ? current : undefined)
        } catch {
          if (!closed) setGoal(undefined)
        }
      }
      createEffect(() => { props.sessionID; void refresh() })
      const clock = setInterval(() => setNow(Date.now()), 1000)
      const poll = setInterval(() => void refresh(), 3000)
      onCleanup(() => { closed = true; clearInterval(clock); clearInterval(poll) })
      const list = createMemo(() => {
        const session = props.sessionID ? context.data.session.get(props.sessionID) : undefined
        const location = session?.location ?? context.location ?? context.data.location.default()
        return rows({
          sessions: children(),
          parentID: props.sessionID,
          models: context.data.location.model.list(location) ?? [],
          now: now(),
        })
      })
      const shellList = createMemo(() => {
        const owners: Record<string, string> = {}
        if (props.sessionID) owners[props.sessionID] = ""
        for (const row of list()) owners[row.id] = `${row.agent}: ${row.title}`
        return shellRows({ shells: shells(), owners, now: now() })
      })
      const muted = () => context.theme.text.muted
      return <box flexDirection="column">
          <Show when={goal()}>{(g) =>
            <box flexDirection="column" paddingBottom={1}>
              <text><b>Goal</b>{g().status === "active" ? "" : ` (${g().status})`}</text>
              <text wrapMode="word" fg={g().status === "active" ? context.theme.text.base : muted()}>{g().objective}</text>
            </box>
          }</Show>
          <text><b>Subagents</b></text>
          <Show when={error()}><text fg={muted()}>unavailable: {error()}</text></Show>
          <Show when={!error() && list().length === 0}><text fg={muted()}>none</text></Show>
          <For each={list()}>{(row: any) =>
            <box flexDirection="column">
              <text wrapMode="word" fg={row.active ? context.theme.text.base : muted()}>
                {row.active ? "● " : "○ "}{row.agent}: {row.title}
              </text>
              <text fg={muted()}>  {row.model} · {row.effort} · <span style={{ fg: timeColor[row.level as keyof typeof timeColor] ?? muted() }}>{row.level === "crit" ? <b>{row.elapsed}</b> : row.elapsed}</span></text>
            </box>
          }</For>
          <Show when={shellList().length > 0}>
            <box flexDirection="column" paddingTop={1}>
              <text><b>Shells</b></text>
              <For each={shellList()}>{(row: any) =>
                <box flexDirection="column">
                  <text wrapMode="word">$ {row.command}</text>
                  <text fg={muted()}>  <span style={{ fg: timeColor[row.level as keyof typeof timeColor] ?? muted() }}>{row.level === "crit" ? <b>{row.elapsed}</b> : row.elapsed}</span>{row.owner ? ` · ${row.owner}` : ""}</text>
                </box>
              }</For>
            </box>
          </Show>
        </box>
    }
    return context.ui.slot({
      append: "sidebar.content",
      render: (props) => <Subagents sessionID={props.sessionID} />,
    })
  },
})
