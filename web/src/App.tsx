import { FormEvent, useEffect, useState } from "react"

import {
  ConversationClient,
  ConversationSnapshot,
  HttpConversationClient,
  Message,
} from "./conversation"
import "./App.css"

const statusLabels: Record<ConversationSnapshot["status"], string> = {
  collecting_information: "等待补充信息",
  waiting_approval: "等待人工审批",
  completed: "已完成",
  error: "需要协助",
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

  useEffect(() => {
    void client
      .load()
      .then(setSnapshot)
      .catch(() => setSnapshot(setUnavailable()))
  }, [client])

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
      {snapshot?.order ? (
        <p className="order-summary">
          订单：{snapshot.order.orderId}，{snapshot.order.status}，
          {snapshot.order.totalAmount} {snapshot.order.currency}
        </p>
      ) : null}
      {snapshot?.status === "completed" && snapshot.serviceCaseId ? (
        <p className="service-case">模拟申请编号：{snapshot.serviceCaseId}</p>
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
    </main>
  )
}

function setUnavailable() {
  return (current: ConversationSnapshot | null): ConversationSnapshot => ({
    status: "error",
    messages: current?.messages ?? [],
    actionHint: "暂时无法继续处理，请稍后重试或联系人工客服。",
  })
}

function displayStatus(
  snapshot: ConversationSnapshot,
): ConversationSnapshot["status"] {
  return snapshot.status === "completed" && !snapshot.serviceCaseId
    ? "error"
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
