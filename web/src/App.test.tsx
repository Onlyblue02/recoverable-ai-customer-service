import "@testing-library/jest-dom/vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import { App } from "./App"
import { ConversationClient, ConversationSnapshot } from "./conversation"

const collecting: ConversationSnapshot = {
  status: "clarify",
  requestedMode: "fake",
  effectiveMode: "fake",
  modelStatus: "not_used",
  reasonCode: "PLAN_CLARIFICATION_REQUIRED",
  actionHint: "请提供订单号。",
  messages: [],
}

class StubClient implements ConversationClient {
  constructor(
    private readonly snapshot: ConversationSnapshot,
    private readonly fail = false,
  ) {}
  async load() {
    return this.snapshot
  }
  async send() {
    if (this.fail) throw new Error("host=db")
    return this.snapshot
  }
}

class DeferredClient implements ConversationClient {
  resolve?: (value: ConversationSnapshot) => void
  async load() {
    return collecting
  }
  send() {
    return new Promise<ConversationSnapshot>((resolve) => {
      this.resolve = resolve
    })
  }
}

afterEach(cleanup)

describe("App", () => {
  it("shows collecting, approval, completed, and safe error states", async () => {
    const { rerender } = render(<App client={new StubClient(collecting)} />)
    expect(await screen.findByText("等待补充信息")).toBeVisible()
    rerender(
      <App
        client={new StubClient({ ...collecting, status: "waiting_approval" })}
      />,
    )
    expect(await screen.findByText("等待人工审批")).toBeVisible()
    rerender(
      <App
        client={
          new StubClient({
            ...collecting,
            status: "completed",
            serviceCaseId: "SC-SIM-001",
          })
        }
      />,
    )
    expect(await screen.findByText("已完成")).toBeVisible()
    expect(screen.getByText(/SC-SIM-001/)).toBeVisible()
    rerender(<App client={new StubClient(collecting, true)} />)
    fireEvent.change(await screen.findByLabelText("输入消息"), {
      target: { value: "退货" },
    })
    fireEvent.click(screen.getByRole("button", { name: "发送" }))
    expect(await screen.findByText("安全停止")).toBeVisible()
    expect(screen.queryByText("host=db")).not.toBeInTheDocument()
  })

  it("shows processing and prevents a duplicate quick submission", async () => {
    const client = new DeferredClient()
    render(<App client={client} />)
    fireEvent.change(await screen.findByLabelText("输入消息"), {
      target: { value: "退货" },
    })
    fireEvent.click(screen.getByRole("button", { name: "发送" }))
    expect(await screen.findByText("处理中，请稍候。")).toBeVisible()
    expect(screen.getByRole("button", { name: "发送中…" })).toBeDisabled()
    client.resolve?.(collecting)
  })
})
