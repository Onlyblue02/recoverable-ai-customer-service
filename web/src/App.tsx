import { FormEvent, useEffect, useState } from "react"

import {
  ConversationClient,
  ConversationSnapshot,
  HttpConversationClient,
  Message,
  AgentMode,
  ModeOption,
} from "./conversation"
import "./App.css"
import { ApprovalWorkbench } from "./ApprovalWorkbench"

const statusLabels: Record<ConversationSnapshot["status"], string> = {
  collecting_information: "等待补充信息",
  clarify: "等待补充信息",
  waiting_approval: "等待人工审批",
  completed: "已完成",
  escalate: "转人工处理",
  failed_safe: "安全停止",
}

const defaultClient = new HttpConversationClient()

export function App({
  client = defaultClient,
}: {
  client?: ConversationClient
}) {
  const [snapshot, setSnapshot] = useState<ConversationSnapshot | null>(null)
  const [text, setText] = useState("")
  const [sending, setSending] = useState(false)
  const [modes, setModes] = useState<ModeOption[]>([
    { id: "fake", configured: true, selectable: true },
  ])

  useEffect(() => {
    void client
      .modes?.()
      .then(setModes)
      .catch(() => undefined)
    void client
      .load()
      .then(setSnapshot)
      .catch(() => setSnapshot(setUnavailable()))
  }, [client])

  async function changeMode(mode: AgentMode) {
    if (!client.start) return
    try {
      setSnapshot(await client.start(mode))
    } catch {
      setSnapshot(setUnavailable())
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const message = text.trim()
    if (!message || sending) return
    setSending(true)
    try {
      setSnapshot(await client.send(message))
      setText("")
    } catch {
      setSnapshot(setUnavailable())
    } finally {
      setSending(false)
    }
  }

  return (
    <main className="app-shell">
      <header>
        <p className="eyebrow">RACS · 消费者服务</p>
        <h1>售后对话</h1>
        <label htmlFor="agent-mode">Agent 模式</label>
        <select
          id="agent-mode"
          value={snapshot?.requestedMode ?? "fake"}
          onChange={(event) => void changeMode(event.target.value as AgentMode)}
        >
          {modes.map((mode) => (
            <option key={mode.id} value={mode.id} disabled={!mode.selectable}>
              {mode.id === "fake" ? "合成演示（Fake）" : "DeepSeek"}
              {!mode.configured ? "（未配置）" : ""}
            </option>
          ))}
        </select>
        <span className="mode-status">
          当前：
          {snapshot?.effectiveMode === "deepseek" ? "DeepSeek" : "合成演示"}；
          模型状态：{snapshot?.modelStatus ?? "not_used"}
        </span>
        <span className="status" aria-label="当前处理状态">
          {snapshot ? statusLabels[displayStatus(snapshot)] : "正在加载"}
        </span>
      </header>
      <section className="conversation" aria-label="会话记录">
        {snapshot?.messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
      </section>
      <aside className="hint" aria-label="下一步提示">
        {snapshot?.actionHint}
      </aside>
      {snapshot?.status === "completed" && snapshot.serviceCaseId ? (
        <p className="service-case">模拟申请编号：{snapshot.serviceCaseId}</p>
      ) : null}
      {snapshot?.orderEvidence ? (
        <aside className="order-evidence" aria-label="订单依据">
          <strong>订单依据</strong>
          <p>
            订单 {snapshot.orderEvidence.orderId}；已确认状态：
            {snapshot.orderEvidence.confirmedStatus}
            ；来源：受控的已授权订单记录。
          </p>
        </aside>
      ) : null}
      <form onSubmit={submit} className="composer">
        <label htmlFor="message">输入消息</label>
        <textarea
          id="message"
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="例如：我想了解退货政策"
          rows={3}
        />
        <button type="submit" disabled={!text.trim() || sending}>
          {sending ? "发送中…" : "发送"}
        </button>
        {sending ? <p role="status">处理中，请稍候。</p> : null}
      </form>
      <ApprovalWorkbench />
    </main>
  )
}

function setUnavailable() {
  return (current: ConversationSnapshot | null): ConversationSnapshot => ({
    status: "failed_safe",
    requestedMode: current?.requestedMode ?? "fake",
    effectiveMode: current?.effectiveMode ?? "fake",
    modelStatus: "unavailable",
    reasonCode: "HTTP_UNAVAILABLE",
    messages: current?.messages ?? [],
    actionHint: "暂时无法继续处理，请稍后重试或联系人工客服。",
  })
}

function displayStatus(
  snapshot: ConversationSnapshot,
): ConversationSnapshot["status"] {
  return snapshot.status === "completed" && !snapshot.serviceCaseId
    ? "completed"
    : snapshot.status
}

function MessageBubble({ message }: { message: Message }) {
  return (
    <article className={`message ${message.role}`}>
      <strong>{message.role === "assistant" ? "客服助手" : "你"}</strong>
      <p>{message.content}</p>
      {message.citations?.map((citation) => (
        <p className="citation" key={citation.policyId}>
          政策来源：{citation.title}（{citation.policyId}）
        </p>
      ))}
    </article>
  )
}
