import type { CopilotApproval } from '@/types/accountCopilot'

export function isApprovalPending(approval: Pick<CopilotApproval, 'status'>): boolean {
  return approval.status === 'pending' || approval.status === 'awaiting_approval'
}

export function approvalButtonState(approval: Pick<CopilotApproval, 'status'>, approving = false) {
  const pending = isApprovalPending(approval)
  return {
    approveDisabled: approving || !pending,
    rejectDisabled: approving || !pending,
  }
}
