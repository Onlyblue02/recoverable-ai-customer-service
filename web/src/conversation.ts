export type AgentMode = "fake" | "deepseek"
export type ConversationStatus =
  | "collecting_information"
  | "clarify"
  | "waiting_approval"
  | "completed"
  | "escalate"
  | "failed_safe"

export type Citation = { policyId: string; title: string; source: string }
export type OrderEvidence = {
  orderId: string
  confirmedStatus: string
  source: "controlled_authorized_order_record"
}
export type Message = {
  id: string
  role: "user" | "assistant"
  content: string
  citations?: Citation[]
}
export type ModeOption = {
  id: AgentMode
  configured: boolean
  selectable: boolean
  reasonCode?: string
}
export type ConversationSnapshot = {
  status: ConversationStatus
  requestedMode: AgentMode
  effectiveMode: AgentMode
  modelStatus: string
  reasonCode: string
  messages: Message[]
  actionHint: string
  serviceCaseId?: string
  orderEvidence?: OrderEvidence
  order?: {
    orderId: string
    status: string
    totalAmount: string
    currency: string
  }
}
export interface ConversationClient {
  load(mode?: AgentMode): Promise<ConversationSnapshot>
  send(message: string): Promise<ConversationSnapshot>
  modes?(): Promise<ModeOption[]>
  start?(mode: AgentMode): Promise<ConversationSnapshot>
}

type ServerResponse = {
  conversation_id: string
  requested_mode?: AgentMode
  effective_mode?: AgentMode
  agent_status?: ConversationStatus
  model_status?: string
  reason_code?: string
  status?: string
  action_hint: string
  service_case_id: string | null
  order_evidence?: {
    order_id: string
    confirmed_status: string
    source: "controlled_authorized_order_record"
  } | null
  order?: {
    order_id: string
    status: string
    total_amount: string
    currency: string
  } | null
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
  constructor(
    private readonly baseUrl = "/api/v1/conversations",
    private readonly fetcher: Fetcher = globalThis.fetch.bind(globalThis),
    private readonly storage:
      ConversationStorage | undefined = browserStorage(),
  ) {}

  async modes(): Promise<ModeOption[]> {
    const response = await this.fetcher("/api/v1/agent/modes")
    if (!response.ok) throw new Error("agent modes unavailable")
    const body = (await response.json()) as {
      modes: Array<{
        id: AgentMode
        configured: boolean
        selectable: boolean
        reason_code?: string
      }>
    }
    return body.modes.map((item) => ({
      id: item.id,
      configured: item.configured,
      selectable: item.selectable,
      reasonCode: item.reason_code,
    }))
  }

  async load(mode: AgentMode = "fake"): Promise<ConversationSnapshot> {
    if (this.snapshot) return this.snapshot
    const remembered = this.conversationId ?? this.readRememberedId()
    if (remembered) {
      const response = await this.fetcher(`${this.baseUrl}/${remembered}`)
      if (response.ok) return this.apply(await this.json(response))
      this.forgetRememberedId()
    }
    return this.start(mode)
  }

  async start(mode: AgentMode): Promise<ConversationSnapshot> {
    const response = await this.fetcher(this.baseUrl, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ mode }),
    })
    this.snapshot = undefined
    return this.apply(await this.json(response))
  }

  async send(message: string): Promise<ConversationSnapshot> {
    if (!this.conversationId) await this.load()
    const response = await this.fetcher(
      `${this.baseUrl}/${this.conversationId}/messages`,
      {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
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
    try {
      this.storage?.setItem(sessionKey, result.conversation_id)
    } catch {
      /* optional */
    }
    this.snapshot = {
      status: result.agent_status ?? legacyStatus(result.status),
      requestedMode: result.requested_mode ?? "fake",
      effectiveMode: result.effective_mode ?? "fake",
      modelStatus: result.model_status ?? "not_used",
      reasonCode: result.reason_code ?? "LEGACY_RESPONSE",
      actionHint: result.action_hint,
      serviceCaseId: result.service_case_id ?? undefined,
      orderEvidence: result.order_evidence
        ? {
            orderId: result.order_evidence.order_id,
            confirmedStatus: result.order_evidence.confirmed_status,
            source: result.order_evidence.source,
          }
        : undefined,
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
  private readRememberedId() {
    try {
      return this.storage?.getItem(sessionKey) ?? undefined
    } catch {
      return undefined
    }
  }
  private forgetRememberedId() {
    try {
      this.storage?.removeItem(sessionKey)
    } catch {
      /* optional storage */
    }
  }
}

function browserStorage(): ConversationStorage | undefined {
  if (typeof window === "undefined") return undefined
  try {
    return window.localStorage
  } catch {
    return undefined
  }
}

function legacyStatus(status?: string): ConversationStatus {
  if (status === "completed") return "completed"
  if (status === "requires_approval") return "waiting_approval"
  return "collecting_information"
}
