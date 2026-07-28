import "@testing-library/jest-dom/vitest"
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"

import {
  Approval,
  ApprovalClient,
  ApprovalWorkbench,
} from "./ApprovalWorkbench"

const task: Approval = {
  approvalId: "APR-SIM-001",
  status: "pending",
  version: 1,
  summary: "高风险退货",
  orderId: "ORD-HIGH-VALUE-001",
  orderStatus: "delivered",
  totalAmount: "9999.00",
  currency: "CNY",
  orderItemId: "ITEM-HIGH-001",
  policies: [
    {
      policyId: "POL-ACTIVE-STANDARD-001",
      version: "1.0.0",
      title: "标准退货政策",
      source: "policy://returns/standard",
    },
  ],
  eligibilityStatus: "requires_approval",
  eligibilityConclusion: "requires_approval",
  ruleVersion: "1.0.0",
  matchedRules: ["HIGH_VALUE_REQUIRES_APPROVAL"],
  riskReasons: ["HIGH_VALUE_ORDER"],
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it("shows only the reviewable evidence whitelist and makes a task terminal", async () => {
  const client: ApprovalClient = {
    list: async () => [task],
    decide: async (_id, input) => ({
      ...task,
      status: "rejected",
      version: 2,
      decision: input.decision,
      note: input.note,
    }),
  }
  render(<ApprovalWorkbench client={client} />)

  expect(
    await screen.findByText(/ORD-HIGH-VALUE-001 · delivered · 9999.00 CNY/),
  ).toBeVisible()
  expect(screen.getByText(/POL-ACTIVE-STANDARD-001 \/ 1.0.0/)).toBeVisible()
  expect(
    screen.getByText(
      /requires_approval \/ requires_approval \/ 规则版本 1.0.0/,
    ),
  ).toBeVisible()
  expect(screen.getByText(/HIGH_VALUE_REQUIRES_APPROVAL/)).toBeVisible()
  expect(
    screen.queryByText(/password=|Traceback|decided_by/i),
  ).not.toBeInTheDocument()

  fireEvent.change(screen.getByLabelText("备注"), {
    target: { value: "已复核风险。" },
  })
  fireEvent.change(screen.getByLabelText("决定"), {
    target: { value: "reject" },
  })
  fireEvent.click(screen.getByRole("button", { name: "提交审批" }))

  expect(await screen.findByText("已处理：reject；已复核风险。")).toBeVisible()
  expect(
    screen.queryByRole("button", { name: "提交审批" }),
  ).not.toBeInTheDocument()
})

it("prevents a rapid duplicate decision while the first request is pending", async () => {
  let resolveDecision!: (value: Approval) => void
  const decide = vi.fn(
    () =>
      new Promise<Approval>((resolve) => {
        resolveDecision = resolve
      }),
  )
  const client: ApprovalClient = { list: async () => [task], decide }
  render(<ApprovalWorkbench client={client} />)
  await screen.findByText(/HIGH_VALUE_ORDER/)
  fireEvent.change(screen.getByLabelText("备注"), {
    target: { value: "审批中" },
  })
  const submit = screen.getByRole("button", { name: "提交审批" })

  fireEvent.click(submit)
  fireEvent.click(submit)

  expect(decide).toHaveBeenCalledTimes(1)
  expect(screen.getByRole("status")).toHaveTextContent("处理中")
  resolveDecision({
    ...task,
    status: "approved",
    version: 2,
    decision: "approve",
    note: "审批中",
  })
  expect(await screen.findByText("已处理：approve；审批中")).toBeVisible()
})

it("reloads trusted terminal state after a version conflict", async () => {
  const terminal: Approval = {
    ...task,
    status: "adjusted",
    version: 2,
    decision: "adjust",
    note: "由其他审批人处理",
  }
  const list = vi
    .fn()
    .mockResolvedValueOnce([task])
    .mockResolvedValueOnce([terminal])
  const client: ApprovalClient = {
    list,
    decide: vi
      .fn()
      .mockRejectedValue(new Error("409 internal conflict detail")),
  }
  render(<ApprovalWorkbench client={client} />)
  await screen.findByText(/HIGH_VALUE_ORDER/)
  fireEvent.change(screen.getByLabelText("备注"), {
    target: { value: "尝试提交" },
  })
  fireEvent.click(screen.getByRole("button", { name: "提交审批" }))

  expect(
    await screen.findByText("已处理：adjust；由其他审批人处理"),
  ).toBeVisible()
  expect(list).toHaveBeenCalledTimes(2)
  expect(screen.queryByText(/internal conflict detail/)).not.toBeInTheDocument()
})

it("keeps the default HTTP client stable across rerenders and reloads once per mount", async () => {
  const wire = {
    approval_id: task.approvalId,
    status: task.status,
    version: task.version,
    conversation_summary: task.summary,
    order: {
      order_id: task.orderId,
      status: task.orderStatus,
      total_amount: task.totalAmount,
      currency: task.currency,
    },
    order_item_id: task.orderItemId,
    policy_citations: task.policies.map((policy) => ({
      policy_id: policy.policyId,
      policy_version: policy.version,
      title: policy.title,
      source: policy.source,
    })),
    eligibility: {
      status: task.eligibilityStatus,
      eligibility: task.eligibilityConclusion,
      rule_version: task.ruleVersion,
      matched_rule_ids: task.matchedRules,
    },
    risk_reasons: task.riskReasons,
    decision: null,
    note: null,
    recommendation: null,
  }
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => [wire],
  })
  vi.stubGlobal("fetch", fetchMock)
  const first = render(<ApprovalWorkbench />)
  await screen.findByText(/HIGH_VALUE_ORDER/)
  first.rerender(<ApprovalWorkbench />)
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))

  first.unmount()
  render(<ApprovalWorkbench />)
  await screen.findByText(/HIGH_VALUE_ORDER/)
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

it("shows a safe actionable message when the default HTTP load fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new Error("password=secret host=db.internal")),
  )
  render(<ApprovalWorkbench />)

  expect(
    await screen.findByText("暂时无法加载审批任务，请稍后重试或联系主管。"),
  ).toBeVisible()
  expect(
    screen.queryByText(/password=secret|db\.internal/),
  ).not.toBeInTheDocument()
})
