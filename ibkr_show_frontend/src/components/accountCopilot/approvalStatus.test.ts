import { describe, expect, it } from 'vitest'

import { approvalButtonState, isApprovalPending } from './approvalStatus'
import type { CopilotApproval } from '@/types/accountCopilot'

function approval(status: CopilotApproval['status']): Pick<CopilotApproval, 'status'> {
  return { status }
}

describe('approval button state', () => {
  it('keeps approve and reject clickable for pending approvals', () => {
    expect(isApprovalPending(approval('pending'))).toBe(true)
    expect(approvalButtonState(approval('pending'))).toEqual({
      approveDisabled: false,
      rejectDisabled: false,
    })
  })

  it('keeps approve and reject clickable for awaiting_approval approvals', () => {
    expect(isApprovalPending(approval('awaiting_approval'))).toBe(true)
    expect(approvalButtonState(approval('awaiting_approval'))).toEqual({
      approveDisabled: false,
      rejectDisabled: false,
    })
  })

  it.each(['approved', 'rejected', 'expired'] as const)('disables buttons for %s approvals', (status) => {
    expect(isApprovalPending(approval(status))).toBe(false)
    expect(approvalButtonState(approval(status))).toEqual({
      approveDisabled: true,
      rejectDisabled: true,
    })
  })
})
