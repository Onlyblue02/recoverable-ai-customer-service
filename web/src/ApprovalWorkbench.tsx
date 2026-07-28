import { FormEvent, useCallback, useEffect, useRef, useState } from "react"

export type PolicyEvidence = {
  policyId: string
  version: string
  title: string
  source: string
}

export type Approval = {
  approvalId: string
  status: "pending" | "approved" | "adjusted" | "rejected"
  version: number
  summary: string
  orderId: string
  orderStatus: string
  totalAmount: string
  currency: string
  orderItemId: string
  policies: PolicyEvidence[]
  eligibilityStatus: string
  eligibilityConclusion: string
  ruleVersion: string
  matchedRules: string[]
  riskReasons: string[]
  decision?: string
  note?: string
  recommendation?: string
}

export interface ApprovalClient {
  list(): Promise<Approval[]>
  decide(
    id: string,
    input: {
      decision: string
      note: string
      recommendation?: string
      expectedVersion: number
    },
  ): Promise<Approval>
}

// eslint-disable-next-line react-refresh/only-export-components
export class HttpApprovalClient implements ApprovalClient {
  async list(): Promise<Approval[]> {
    const response = await fetch("/api/v1/approvals")
    if (!response.ok) throw new Error("approval unavailable")
    return ((await response.json()) as unknown[]).map(toApproval)
  }

  async decide(
    id: string,
    input: {
      decision: string
      note: string
      recommendation?: string
      expectedVersion: number
    },
  ): Promise<Approval> {
    const response = await fetch(`/api/v1/approvals/${id}/decisions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        decision: input.decision,
        note: input.note,
        recommendation: input.recommendation,
        expected_version: input.expectedVersion,
      }),
    })
    if (!response.ok) throw new Error("approval unavailable")
    return toApproval(await response.json())
  }
}

const defaultApprovalClient = new HttpApprovalClient()

type ApprovalWire = {
  approval_id: string
  status: Approval["status"]
  version: number
  conversation_summary: string
  order: {
    order_id: string
    status: string
    total_amount: string
    currency: string
  }
  order_item_id: string
  policy_citations: {
    policy_id: string
    policy_version: string
    title: string
    source: string
  }[]
  eligibility: {
    status: string
    eligibility: string
    rule_version: string
    matched_rule_ids: string[]
  }
  risk_reasons: string[]
  decision: string | null
  note: string | null
  recommendation: string | null
}

function toApproval(raw: unknown): Approval {
  const task = raw as ApprovalWire
  return {
    approvalId: task.approval_id,
    status: task.status,
    version: task.version,
    summary: task.conversation_summary,
    orderId: task.order.order_id,
    orderStatus: task.order.status,
    totalAmount: task.order.total_amount,
    currency: task.order.currency,
    orderItemId: task.order_item_id,
    policies: task.policy_citations.map((policy) => ({
      policyId: policy.policy_id,
      version: policy.policy_version,
      title: policy.title,
      source: policy.source,
    })),
    eligibilityStatus: task.eligibility.status,
    eligibilityConclusion: task.eligibility.eligibility,
    ruleVersion: task.eligibility.rule_version,
    matchedRules: task.eligibility.matched_rule_ids,
    riskReasons: task.risk_reasons,
    decision: task.decision ?? undefined,
    note: task.note ?? undefined,
    recommendation: task.recommendation ?? undefined,
  }
}

export function ApprovalWorkbench({
  client = defaultApprovalClient,
}: {
  client?: ApprovalClient
}) {
  const [items, setItems] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const [note, setNote] = useState("")
  const [recommendation, setRecommendation] = useState("")
  const [state, setState] = useState("加载中")
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)

  const refresh = useCallback(async () => {
    const tasks = await client.list()
    setItems(tasks)
    setSelected((current) => {
      if (!current) return tasks[0] ?? null
      return (
        tasks.find((task) => task.approvalId === current.approvalId) ??
        tasks[0] ??
        null
      )
    })
    setState(tasks.length ? "待人工审批" : "暂无待处理任务")
  }, [client])

  useEffect(() => {
    void client
      .list()
      .then((tasks) => {
        setItems(tasks)
        setSelected(tasks[0] ?? null)
        setState(tasks.length ? "待人工审批" : "暂无待处理任务")
      })
      .catch(() => setState("暂时无法加载审批任务，请稍后重试或联系主管。"))
  }, [client])

  async function decide(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (
      !selected ||
      selected.status !== "pending" ||
      !note.trim() ||
      submittingRef.current
    )
      return
    const decision = String(new FormData(event.currentTarget).get("decision"))
    submittingRef.current = true
    setSubmitting(true)
    setState("处理中")
    try {
      const updated = await client.decide(selected.approvalId, {
        decision,
        note,
        recommendation: decision === "adjust" ? recommendation : undefined,
        expectedVersion: selected.version,
      })
      setItems((current) =>
        current.map((item) =>
          item.approvalId === updated.approvalId ? updated : item,
        ),
      )
      setSelected(updated)
      setState("审批决定已保存")
    } catch {
      try {
        await refresh()
      } catch {
        setState("审批未保存，请稍后重试或联系主管。")
      }
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  return (
    <section className="approval-workbench" aria-label="人工审批工作台">
      <h2>人工审批工作台</h2>
      <p role="status">{state}</p>
      <div className="approval-grid">
        <aside>
          <h3>审批列表</h3>
          {items.map((item) => (
            <button key={item.approvalId} onClick={() => setSelected(item)}>
              {item.approvalId} · {item.status}
            </button>
          ))}
        </aside>
        {selected ? (
          <article>
            <h3>{selected.approvalId}</h3>
            <p>用户诉求：{selected.summary}</p>
            <p>
              订单：{selected.orderId} · {selected.orderStatus} ·{" "}
              {selected.totalAmount} {selected.currency}
            </p>
            <p>商品行：{selected.orderItemId}</p>
            {selected.policies.map((policy) => (
              <p key={policy.policyId}>
                政策证据：{policy.policyId} / {policy.version} / {policy.title}{" "}
                / {policy.source}
              </p>
            ))}
            <p>
              资格：{selected.eligibilityStatus} /{" "}
              {selected.eligibilityConclusion} / 规则版本 {selected.ruleVersion}
            </p>
            <p>命中规则：{selected.matchedRules.join("、")}</p>
            <p>升级原因：{selected.riskReasons.join("、")}</p>
            <p>当前状态：{selected.status}</p>
            {selected.status === "pending" ? (
              <form onSubmit={decide}>
                <label>
                  决定
                  <select name="decision" disabled={submitting}>
                    <option value="approve">批准</option>
                    <option value="adjust">调整</option>
                    <option value="reject">拒绝</option>
                  </select>
                </label>
                <label>
                  备注
                  <textarea
                    value={note}
                    disabled={submitting}
                    onChange={(event) => setNote(event.target.value)}
                  />
                </label>
                <label>
                  调整建议
                  <textarea
                    value={recommendation}
                    disabled={submitting}
                    onChange={(event) => setRecommendation(event.target.value)}
                  />
                </label>
                <button disabled={!note.trim() || submitting}>
                  {submitting ? "处理中…" : "提交审批"}
                </button>
              </form>
            ) : (
              <p>
                已处理：{selected.decision}；{selected.note}
              </p>
            )}
          </article>
        ) : null}
      </div>
    </section>
  )
}
