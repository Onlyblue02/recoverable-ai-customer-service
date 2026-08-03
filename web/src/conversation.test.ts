import { describe, expect, it, vi } from "vitest"

import { ConversationStorage, HttpConversationClient } from "./conversation"

class MemoryStorage implements ConversationStorage {
  private values = new Map<string, string>()

  getItem(key: string) {
    return this.values.get(key) ?? null
  }

  setItem(key: string, value: string) {
    this.values.set(key, value)
  }

  removeItem(key: string) {
    this.values.delete(key)
  }
}

function response(body: object, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

const welcome = {
  conversation_id: "session-1",
  status: "collecting_information",
  message: "可以咨询退货政策、查询订单或申请退货。",
  action_hint: "请输入政策问题、订单号或退货诉求。",
  citations: [],
  order: null,
  service_case_id: null,
  messages: [
    {
      id: "assistant-0",
      role: "assistant",
      content: "可以咨询退货政策、查询订单或申请退货。",
      citations: [],
    },
  ],
} as const

describe("HttpConversationClient", () => {
  it("renders policy and authorized order information returned by the HTTP conversation API", async () => {
    let call = 0
    const client = new HttpConversationClient(
      "/conversation",
      async () => {
        call += 1
        if (call === 1) return response(welcome)
        if (call === 2) {
          return response({
            ...welcome,
            message: "当前政策允许符合条件的退货。",
            citations: [
              {
                policy_id: "POL-ACTIVE-STANDARD-001",
                title: "标准退货政策",
                source: "synthetic://policy",
              },
            ],
            messages: [
              ...welcome.messages,
              {
                id: "user-1",
                role: "user",
                content: "我想了解退货政策",
                citations: [],
              },
              {
                id: "assistant-2",
                role: "assistant",
                content: "当前政策允许符合条件的退货。",
                citations: [
                  {
                    policy_id: "POL-ACTIVE-STANDARD-001",
                    title: "标准退货政策",
                    source: "synthetic://policy",
                  },
                ],
              },
            ],
          })
        }
        return response({
          ...welcome,
          message: "已找到订单。",
          order: {
            order_id: "ORD-NORMAL-001",
            status: "delivered",
            total_amount: "129.00",
            currency: "CNY",
          },
          messages: welcome.messages,
        })
      },
      new MemoryStorage(),
    )

    await client.load()
    const policy = await client.send("我想了解退货政策")
    const order = await client.send("查询订单 ORD-NORMAL-001")

    expect(policy.messages.at(-1)?.citations?.[0]?.policyId).toBe(
      "POL-ACTIVE-STANDARD-001",
    )
    expect(order.order).toEqual({
      orderId: "ORD-NORMAL-001",
      status: "delivered",
      totalAmount: "129.00",
      currency: "CNY",
    })
  })

  it("restores a remembered session and replaces an unknown remembered session safely", async () => {
    const storage = new MemoryStorage()
    storage.setItem("racs-consumer-conversation-id", "session-1")
    const restored = new HttpConversationClient(
      "/conversation",
      async () => response(welcome),
      storage,
    )
    expect((await restored.load()).messages).toHaveLength(1)

    const unknownStorage = new MemoryStorage()
    unknownStorage.setItem("racs-consumer-conversation-id", "gone")
    let calls = 0
    const replaced = new HttpConversationClient(
      "/conversation",
      async () => {
        calls += 1
        return calls === 1 ? response({}, 404) : response(welcome)
      },
      unknownStorage,
    )
    expect((await replaced.load()).messages[0]?.content).toBe(welcome.message)
    expect(unknownStorage.getItem("racs-consumer-conversation-id")).toBe(
      "session-1",
    )
  })

  it("rejects network and message failures without exposing their response body", async () => {
    const unavailable = new HttpConversationClient(
      "/conversation",
      async () => {
        throw new Error("network disconnected")
      },
      new MemoryStorage(),
    )
    await expect(unavailable.load()).rejects.toThrow("network disconnected")

    let call = 0
    const expired = new HttpConversationClient(
      "/conversation",
      async () => {
        call += 1
        return call === 1
          ? response(welcome)
          : response({ detail: "internal host=db" }, 404)
      },
      new MemoryStorage(),
    )
    await expired.load()
    await expect(expired.send("我要退货")).rejects.toThrow(
      "conversation unavailable",
    )
  })

  it("keeps the active conversation usable when browser storage is unavailable", async () => {
    const unavailableStorage: ConversationStorage = {
      getItem() {
        throw new Error("storage denied")
      },
      setItem() {
        throw new Error("storage denied")
      },
      removeItem() {
        throw new Error("storage denied")
      },
    }
    const client = new HttpConversationClient(
      "/conversation",
      async () => response(welcome),
      unavailableStorage,
    )

    expect((await client.load()).status).toBe("collecting_information")
  })

  it("binds the default browser fetch to the global browser context", async () => {
    vi.stubGlobal("fetch", function (this: unknown) {
      expect(this).toBe(globalThis)
      return Promise.resolve(response(welcome))
    })
    try {
      const client = new HttpConversationClient(
        "/conversation",
        undefined,
        new MemoryStorage(),
      )
      expect((await client.load()).status).toBe("collecting_information")
    } finally {
      vi.unstubAllGlobals()
    }
  })
})
