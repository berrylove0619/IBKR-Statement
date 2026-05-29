import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchEmailSettings, sendEmailTest, sendLatestAccountSnapshot, sendLatestDailyReview, updateEmailSettings } from '@/api/adminEmail'

describe('adminEmail api', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('loads email settings and keeps password masked', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          enabled: true,
          smtp_host: 'smtp.example.com',
          smtp_port: 465,
          smtp_username: 'mailer@example.com',
          smtp_password_masked: '****3456',
          has_smtp_password: true,
          smtp_use_ssl: true,
          smtp_use_starttls: false,
          email_from: 'mailer@example.com',
          email_to: 'me@example.com',
          subject_prefix: 'IBKR每日持仓复盘',
          site_base_url: '',
          config_file: '/tmp/email.json',
          daily_review_email_enabled: true,
          daily_review_email_to: 'review@example.com',
          daily_review_subject_prefix: 'IBKR每日持仓复盘',
          daily_snapshot_email_enabled: false,
          daily_snapshot_email_to: '',
          daily_snapshot_subject_prefix: 'IBKR Daily Snapshot',
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const settings = await fetchEmailSettings()

    expect(settings.smtp_password_masked).toBe('****3456')
    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8000/api/admin/email/settings', expect.objectContaining({ credentials: 'include' }))
  })

  it('updates settings and omits blank smtp password from payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ settings: { smtp_host: '' }, message: 'ok' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await updateEmailSettings({
      smtp_host: '',
      smtp_port: 465,
      smtp_username: '',
      smtp_use_ssl: true,
      smtp_use_starttls: false,
      email_from: '',
      daily_review_email_enabled: false,
      daily_review_email_to: '',
      daily_snapshot_email_enabled: false,
      daily_snapshot_email_to: '',
    })

    const requestInit = fetchMock.mock.calls[0][1] as RequestInit
    expect(requestInit.method).toBe('PUT')
    expect(JSON.parse(String(requestInit.body))).not.toHaveProperty('smtp_password')
  })

  it('posts test email request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true, message: 'sent', sent_to: ['me@example.com'], sent_at: 'now' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await sendEmailTest()

    expect(result.success).toBe(true)
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/admin/email/test',
      expect.objectContaining({ method: 'POST', credentials: 'include' }),
    )
  })

  it('posts send-latest-daily-review request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true, sent: true, report_date: '2026-05-19', message: '发送成功' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await sendLatestDailyReview()

    expect(result.success).toBe(true)
    expect(result.sent).toBe(true)
    expect(result.report_date).toBe('2026-05-19')
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/admin/email/send-latest-daily-review',
      expect.objectContaining({ method: 'POST', credentials: 'include' }),
    )
  })

  it('posts send-latest-account-snapshot request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true, sent: true, report_date: '2026-05-19', message: '发送成功' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await sendLatestAccountSnapshot()

    expect(result.success).toBe(true)
    expect(result.sent).toBe(true)
    expect(result.report_date).toBe('2026-05-19')
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/admin/email/send-latest-account-snapshot',
      expect.objectContaining({ method: 'POST', credentials: 'include' }),
    )
  })
})