import { useEffect, useState } from 'react'
import { api } from '../api.js'
import usePoll from '../usePoll.js'

// "01_quote_dallas_returns.json" -> "Quote dallas returns"
const sampleLabel = (file) => {
  const s = file.replace(/\.json$/, '').replace(/^(email_)?\d+_?/, '').replace(/_/g, ' ')
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : file.replace(/\.json$/, '')
}

// snake_case -> "Snake case"
function humanize(key) {
  const s = String(key).replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function formatTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

// What the agent wants to do because of this email, with the decision right here.
function ActionRow({ action, onDecide, busy }) {
  const status = action.status
  return (
    <div className={`card stack email-action ${status}`} style={{ gap: 6 }}>
      <div className="row between">
        <b className="h3">{action.title}</b>
        <span className={`badge ${status === 'pending' ? 'warn' : status === 'done' ? 'ok' : 'bad'}`}>
          {status === 'pending' ? 'Needs your OK' : status === 'done' ? 'Done' : status}
        </span>
      </div>
      <span className="small">{action.summary}</span>
      {action.confidence != null && <span className="small muted">{Math.round(action.confidence * 100)}% confident · {action.reasoning?.split('\n')[0]}</span>}
      {status === 'pending' && (
        <div className="row">
          <button className="btn success small" disabled={busy} onClick={() => onDecide(action, 'approve')}>Approve</button>
          <button className="btn danger small" disabled={busy} onClick={() => onDecide(action, 'reject')}>Reject</button>
        </div>
      )}
      {status === 'done' && action.result?.summary && <span className="small" style={{ color: 'var(--success)' }}>{action.result.summary}</span>}
    </div>
  )
}

function MailDetail({ email, drafts, actionsById, onDecide, busy }) {
  const fields = Object.entries(email.extracted || {})
  const actions = (email.action_ids || []).map((id) => actionsById[id] || { action_id: id, title: id, status: 'unknown' })

  return (
    <div className="card stack mail-open">
      <div>
        <div className="section-title" style={{ marginTop: 0 }}>What the agent will do</div>
        {actions.length ? (
          <div className="stack" style={{ gap: 8 }}>
            {actions.map((a) => <ActionRow key={a.action_id} action={a} onDecide={onDecide} busy={busy} />)}
          </div>
        ) : (
          <span className="muted small">Nothing to do for this email.</span>
        )}
      </div>
      <div className="mail-detail">
        <div className="mail-body">{email.body}</div>
        <dl className="fields">
          {fields.map(([key, value]) => (
            <div key={key} style={{ display: 'contents' }}>
              <dt>{humanize(key)}</dt>
              <dd>{String(value)}</dd>
            </div>
          ))}
        </dl>
      </div>


      {drafts.map((d) => (
        <div key={d.id} className="card draft stack" style={{ gap: 6 }}>
          <div className="small muted">To {d.to}</div>
          <div className="h3">{d.subject}</div>
          <div className="mail-body">{d.body}</div>
          <div className="small muted">Draft reply. It is sent only when you approve its action above.</div>
        </div>
      ))}
    </div>
  )
}

export default function InboxPanel({ onToast, onActionsCreated }) {
  const inbox = usePoll(() => api.getInbox(), 5000)
  const outbox = usePoll(() => api.getOutbox(), 5000)
  const samples = usePoll(() => api.getEmailSamples(), 0)
  const allActions = usePoll(() => api.getActions(), 3000)
  const actionsById = Object.fromEntries((allActions.data?.items || []).map((a) => [a.action_id, a]))
  const [deciding, setDeciding] = useState(false)

  async function decide(action, decision) {
    setDeciding(true)
    try {
      if (decision === 'approve') {
        const done = await api.approve(action.action_id)
        onToast(done.result?.summary || `${action.title}: done`, 'success')
      } else {
        await api.reject(action.action_id, 'Rejected from the inbox')
        onToast(`Rejected: ${action.title}`, 'info')
      }
      allActions.refresh()
      onActionsCreated?.()
    } catch (e) {
      onToast(e.message, 'error')
    } finally {
      setDeciding(false)
    }
  }
  const [selectedId, setSelectedId] = useState(null)
  const [running, setRunning] = useState(null)

  const emails = inbox.data?.items || []
  const drafts = outbox.data?.items || []

  // Default-select the first email once the inbox loads.
  useEffect(() => {
    if (!selectedId && emails.length) setSelectedId(emails[0].id)
  }, [selectedId, emails])

  async function simulate(file) {
    setRunning(file)
    try {
      const { email, actions_created } = await api.simulateEmail(file)
      onToast(`New ${humanize(email.kind).toLowerCase()} from ${email.from_name}${actions_created?.length ? ` · ${actions_created.length} action${actions_created.length > 1 ? 's' : ''} for you` : ''}`, 'success')
      await Promise.all([inbox.refresh(), outbox.refresh()])
      setSelectedId(email.id)
      if (actions_created?.length) onActionsCreated()
    } catch (e) {
      onToast(e.message, 'error')
    } finally {
      setRunning(null)
    }
  }

  return (
    <div>
      <div className="section-title" style={{ marginTop: 0 }}>Simulate an incoming email</div>
      <div className="sim-buttons">
        {(samples.data?.items || []).map((f) => (
          <button key={f} className="btn small" disabled={running !== null} onClick={() => simulate(f)} title={f}>
            {running === f ? 'Reading…' : sampleLabel(f)}
          </button>
        ))}
      </div>

      <div className="section-title">Inbox</div>
      {inbox.loading ? (
        <div className="stack">
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton" />
        </div>
      ) : emails.length === 0 ? (
        <div className="empty">{inbox.error || 'No emails yet. Simulate one above.'}</div>
      ) : (
        <div className="stack">
          {emails.map((m) => {
            const selected = m.id === selectedId
            return (
              <div key={m.id} className="stack">
                <div className={`card mail stack ${selected ? 'selected' : ''}`} style={{ gap: 6 }} onClick={() => setSelectedId(m.id)}>
                  <div className="row between small">
                    <span>{m.from_name || m.from}</span>
                    <span className="muted">{formatTime(m.received_at)}</span>
                  </div>
                  <div className="subject">{m.subject}</div>
                  <div className="row wrap small">
                    <span className="badge">{humanize(m.kind)}</span>
                    <span className="muted num">{Math.round(m.confidence * 100)}%</span>
                    {m.status === 'needs_review' ? (
                      <span className="badge warn">Needs review</span>
                    ) : (
                      <span className="badge ok">Processed</span>
                    )}
                  </div>
                </div>
                {selected && <MailDetail email={m} drafts={drafts.filter((d) => d.in_reply_to === m.id)} actionsById={actionsById} onDecide={decide} busy={deciding} />}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
