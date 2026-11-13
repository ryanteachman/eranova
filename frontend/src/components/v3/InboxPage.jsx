import { useEffect, useState } from 'react'
import { api } from '../../api.js'
import usePoll from '../../usePoll.js'
import './InboxPage.css'

// Full-page inbox: email list · the open email · what the agent will do about it.

const KIND = {
  quote_request: { label: 'Price request', tone: 'blue' },
  washout_cert: { label: 'Washout certificate', tone: 'green' },
  last_load_info: { label: 'Last load info', tone: 'amber' },
  carrier_offer: { label: 'Carrier has a truck', tone: 'blue' },
  other: { label: 'Other', tone: '' },
}
const kindOf = (k) => KIND[k] || { label: String(k || 'other').replace(/_/g, ' '), tone: '' }
const humanize = (key) => {
  const s = String(key).replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}
const sampleLabel = (file) => {
  const s = file.replace(/\.json$/, '').replace(/^(email_)?\d+_?/, '').replace(/_/g, ' ')
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : file
}
const when = (iso) => (iso ? new Date(iso).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' }) : '')
const show = (v) => (v == null || v === '' ? null : typeof v === 'object' ? (Array.isArray(v) ? v.map(show).filter(Boolean).join(', ') : Object.values(v).filter((x) => x != null && typeof x !== 'object').join(', ')) : String(v))

function Action({ action, busy, onDecide }) {
  const s = action.status
  const [open, setOpen] = useState(false)
  return (
    <div className={`ib-action ${s}`}>
      <div className="ib-action-head">
        <b>{action.title}</b>
        <span className={`ib-pill ${s === 'pending' ? 'amber' : s === 'done' ? 'green' : 'red'}`}>
          {s === 'pending' ? 'Needs your OK' : s === 'done' ? 'Done' : humanize(s)}
        </span>
      </div>
      {action.summary && <p>{action.summary}</p>}
      {action.risk?.reasons?.length > 0 && action.status === 'pending' && (
        <p className="ib-held">Auto mode held this for you: {action.risk.reasons.join(' · ')}</p>
      )}
      {action.confidence != null && <span className="ib-muted">{Math.round(action.confidence * 100)}% confident</span>}
      {action.reasoning && (
        <>
          <button className="ib-why" onClick={() => setOpen((o) => !o)}>{open ? 'Hide reasoning' : 'Show reasoning'}</button>
          {open && <p className="ib-reasoning">{action.reasoning}</p>}
        </>
      )}
      {s === 'pending' && (
        <div className="ib-buttons">
          <button className="ib-approve" disabled={busy} onClick={() => onDecide(action, 'approve')}>Approve</button>
          <button className="ib-reject" disabled={busy} onClick={() => onDecide(action, 'reject')}>Reject</button>
        </div>
      )}
      {s === 'done' && action.result?.summary && <span className="ib-done">{action.result.summary}</span>}
    </div>
  )
}

export default function InboxPage({ onToast, onActionsChanged, onApproved, onClose }) {
  const inbox = usePoll(() => api.getInbox(), 5000)
  const outbox = usePoll(() => api.getOutbox(), 5000)
  const actions = usePoll(() => api.getActions(), 3000)
  const samples = usePoll(() => api.getEmailSamples(), 0)
  const [selectedId, setSelectedId] = useState(null)
  const [running, setRunning] = useState(null)
  const [busy, setBusy] = useState(false)

  const emails = inbox.data?.items || []
  const byId = Object.fromEntries((actions.data?.items || []).map((a) => [a.action_id, a]))
  const email = emails.find((e) => e.id === selectedId) || emails[0] || null
  const emailActions = (email?.action_ids || []).map((id) => byId[id] || { action_id: id, title: id, status: 'unknown' })
  const drafts = (outbox.data?.items || []).filter((d) => email && d.in_reply_to === email.id)
  const waiting = emails.reduce((n, e) => n + (e.action_ids || []).filter((id) => byId[id]?.status === 'pending').length, 0)

  useEffect(() => {
    if (!selectedId && emails.length) setSelectedId(emails[0].id)
  }, [selectedId, emails])

  async function simulate(file) {
    setRunning(file)
    try {
      const { email: e, actions_created } = await api.simulateEmail(file)
      onToast(`New ${kindOf(e.kind).label.toLowerCase()} from ${e.from_name}${actions_created?.length ? ` · ${actions_created.length} for you to approve` : ''}`, 'success')
      await Promise.all([inbox.refresh(), outbox.refresh(), actions.refresh()])
      setSelectedId(e.id)
      onActionsChanged?.()
    } catch (err) {
      onToast(err.message, 'error')
    } finally {
      setRunning(null)
    }
  }

  async function decide(action, decision) {
    setBusy(true)
    try {
      if (decision === 'approve') {
        const done = await api.approve(action.action_id)
        if (onApproved) onApproved(done)
        else onToast(done.result?.summary || `${action.title}: done`, 'success')
      } else {
        await api.reject(action.action_id, 'Rejected from the inbox')
        onToast(`Rejected: ${action.title}`, 'info')
      }
      await Promise.all([actions.refresh(), outbox.refresh()])
      onActionsChanged?.()
    } catch (err) {
      onToast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const fields = Object.entries(email?.extracted || {}).map(([k, v]) => [humanize(k), show(v)]).filter(([, v]) => v)

  return (
    <div className="ib">
      <header className="ib-top">
        <div>
          <span className="ib-kicker">Email</span>
          <h2>Inbox {waiting > 0 && <em>{waiting} waiting for you</em>}</h2>
        </div>
        <div className="ib-samples">
          <span className="ib-muted">Try a sample:</span>
          {(samples.data?.items || []).map((f) => (
            <button key={f} disabled={running !== null} onClick={() => simulate(f)} title={f}>
              {running === f ? 'Reading…' : sampleLabel(f)}
            </button>
          ))}
        </div>
        <button className="ib-close" onClick={onClose} aria-label="Close inbox">✕</button>
      </header>

      <div className="ib-cols">
        {/* 1 · the list */}
        <aside className="ib-list">
          {inbox.loading && [0, 1, 2].map((i) => <div key={i} className="ib-skel" />)}
          {!inbox.loading && emails.length === 0 && (
            <div className="ib-empty">
              {inbox.data?.not_connected ? 'The email pipeline is not connected.' : 'No emails yet. Try a sample above.'}
            </div>
          )}
          {emails.map((e) => {
            const k = kindOf(e.kind)
            const pending = (e.action_ids || []).filter((id) => byId[id]?.status === 'pending').length
            return (
              <button key={e.id} className={`ib-row ${email?.id === e.id ? 'on' : ''}`} onClick={() => setSelectedId(e.id)}>
                <div className="ib-row-top">
                  <b>{e.from_name || e.from}</b>
                  <span>{when(e.received_at)}</span>
                </div>
                <span className="ib-subject">{e.subject}</span>
                <div className="ib-row-tags">
                  <span className={`ib-pill ${k.tone}`}>{k.label}</span>
                  {e.status === 'needs_review' && <span className="ib-pill amber">Needs review</span>}
                  {pending > 0 && <span className="ib-pill dark">{pending} to approve</span>}
                </div>
              </button>
            )
          })}
        </aside>

        {/* 2 · the email */}
        <section className="ib-mail">
          {email ? (
            <>
              <span className="ib-muted">{email.from} · {when(email.received_at)}</span>
              <h3>{email.subject}</h3>
              <div className="ib-body">{email.body}</div>
              {fields.length > 0 && (
                <>
                  <h4>What the AI read from it <span className="ib-muted">{Math.round((email.confidence || 0) * 100)}% sure</span></h4>
                  <dl className="ib-fields">
                    {fields.map(([k, v]) => (
                      <div key={k}>
                        <dt>{k}</dt>
                        <dd>{v}</dd>
                      </div>
                    ))}
                  </dl>
                </>
              )}
            </>
          ) : (
            <div className="ib-empty">Pick an email.</div>
          )}
        </section>

        {/* 3 · what the agent will do */}
        <aside className="ib-side">
          <h4>What the agent will do</h4>
          {!email && <div className="ib-empty">Nothing selected.</div>}
          {email && emailActions.length === 0 && (
            <div className="ib-empty">{email.status === 'needs_review' ? 'Not enough detail to act on. A person should read this one.' : 'Nothing to do for this email.'}</div>
          )}
          {emailActions.map((a) => <Action key={a.action_id} action={a} busy={busy} onDecide={decide} />)}
          {drafts.map((d) => (
            <div key={d.id} className="ib-draft">
              <span className="ib-muted">Draft reply to {d.to}</span>
              <b>{d.subject}</b>
              <div className="ib-body small">{d.body}</div>
              <span className="ib-muted">{d.status === 'draft' ? 'Sent only after you approve the reply above.' : humanize(d.status)}</span>
            </div>
          ))}
        </aside>
      </div>
    </div>
  )
}
