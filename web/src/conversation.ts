export type ConversationStatus =
  "collecting_information" | "waiting_approval" | "completed" | "error"

export type Citation = {
  policyId: string
  title: string
  source: string
}

export type OrderSummary = {
  orderId: string
  status: string
  totalAmount: string
  currency: string
}

export type Message = {
  id: string
  role: "user" | "assistant"
  content: string
  citations?: Citation[]
}

export type ConversationSnapshot = {
  status: ConversationStatus
  messages: Message[]
  actionHint: string
  order?: OrderSummary
  serviceCaseId?: string
}

export interface ConversationClient {
  load(): Promise<ConversationSnapshot>
  send(message: string): Promise<ConversationSnapshot>
}

type ServerResponse = {
  conversation_id: string
  status: string
  message: string
  action_hint: string
  citations: Array<{ policy_id: string; title: string; source: string }>
  order: {
    order_id: string
    status: string
    total_amount: string
    currency: string
  } | null
  service_case_id: string | null
  messages: Array<{
    id: string
    role: "user" | "assistant"
    content: string
    citations: Array<{ policy_id: string; title: string; source: string }>
  }>
}

type Fetcher = typeof fetch

export type ConversationStorage = Pick<
  Storage,
  "getItem" | "setItem" | "removeItem"
>

const sessionKey = "racs-consumer-conversation-id"

export class HttpConversationClient implements ConversationClient {
  private conversationId?: string
  private snapshot?: ConversationSnapshot
  private loading?: Promise<ConversationSnapshot>

  constructor(
    private readonly baseUrl = "/api/v1/conversations",
    private readonly fetcher: Fetcher = fetch,
    private readonly storage:
      ConversationStorage | undefined = browserStorage(),
  ) {}

  async load(): Promise<ConversationSnapshot> {
    if (this.snapshot) return this.snapshot
    if (this.loading) return this.loading
    this.loading = this.loadSession()
    try {
      return await this.loading
    } finally {
      this.loading = undefined
    }
  }

  private async loadSession(): Promise<ConversationSnapshot> {
    const rememberedId =
      this.conversationId ?? this.storage?.getItem(sessionKey) ?? undefined
    if (rememberedId) {
      const response = await this.fetcher(`${this.baseUrl}/${rememberedId}`)
      if (response.ok) return this.apply(await this.json(response))
      if (response.status !== 404) throw new Error("conversation unavailable")
      this.storage?.removeItem(sessionKey)
      this.conversationId = undefined
    }
    const response = await this.fetcher(this.baseUrl, { method: "POST" })
    return this.apply(await this.json(response))
  }

  async send(message: string): Promise<ConversationSnapshot> {
    if (!this.conversationId) await this.load()
    const response = await this.fetcher(
      `${this.baseUrl}/${this.conversationId}/messages`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message }),
      },
    )
    return this.apply(await this.json(response))
  }

  private async json(response: Response): Promise<ServerResponse> {
    if (!response.ok) throw new Error("conversation unavailable")
    return (await response.json()) as ServerResponse
  }

  private apply(result: ServerResponse): ConversationSnapshot {
    this.conversationId = result.conversation_id
    this.storage?.setItem(sessionKey, this.conversationId)
    this.snapshot = {
      status: statusFrom(result.status),
      actionHint: result.action_hint,
      serviceCaseId: result.service_case_id ?? undefined,
      order: result.order
        ? {
            orderId: result.order.order_id,
            status: result.order.status,
            totalAmount: result.order.total_amount,
            currency: result.order.currency,
          }
        : undefined,
      messages: result.messages.map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
        citations: message.citations.map((citation) => ({
          policyId: citation.policy_id,
          title: citation.title,
          source: citation.source,
        })),
      })),
    }
    return this.snapshot
  }
}

function browserStorage(): ConversationStorage | undefined {
  return typeof window === "undefined" ? undefined : window.localStorage
}

function statusFrom(status: string): ConversationStatus {
  if (status === "completed") return "completed"
  if (status === "requires_approval") return "waiting_approval"
  if (status === "collecting_information") return "collecting_information"
  return "error"
}
