import { useState } from 'react'
import { api, meridianLink } from '../api.js'
import AuditLog from './AuditLog.jsx'

const TIERS = {
  write: { cls: 'badge warn', label: 'Writes to Meridian' },
  external: { cls: 'badge bad', label: 'Sends externally' },
}

const usd = (n) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

function PendingCard({ action, busy, onApprove, onReject }) {
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const tier = TIERS[action.tier] || { cls: 'badge', label: action.tier }
  const pct = Math.round((action.confidence || 0) * 100)

  return (
    <div className="card stack">
      <div className="row between">
        <h3 className="h3">{action.title}</h3>
        <span className={tier.cls}>{tier.label}</span>
      </div>
      <div>{action.summary}</div>
      <div className="row small muted">
        <div className="conf"><i style={{ width: pct + '%' }} /></div>
        {pct}% confident
      </div>
      {action.reasoning && (
        <details className="reasoning">
          <summary>Why</summary>
          <p>{action.reasoning}</p>
        </details>
      )}
      <div className="row">
        <button className="btn success small" disabled={busy} onClick={() => onApprove(action)}>
          Approve
        </button>
        <button className="btn danger small" disabled={busy} onClick={() => setRejecting((r) => !r)}>
          Reject
        </button>
      </div>
      {rejecting && (
        <form
          className="reject-box"
          onSubmit={(e) => {
            e.preventDefault()
            if (reason.trim()) onReject(action, reason.trim())
          }}
        >
          <input
            autoFocus
            placeholder="Reason (required)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <button className="btn danger small" disabled={busy || !reason.trim()}>
            Confirm
          </button>
        </form>
      )}
    </div>
  )
}

function DecidedCard({ action }) {
  if (action.status === 'rejected') {
    return (
      <div className="card result rejected">
        <div className="h3">Rejected {action.title || action.action_id}</div>
        <div className="muted small">Reason: {action.reject_reason}</div>
      </div>
    )
  }

  const r = action.result || {}
  const link = meridianLink(r)
  return (
    <div className="card result stack">
      <div className="h3">{r.summary || `${action.action_id} approved`}</div>
      {(r.sell_total != null || r.gp_pct != null) && (
        <div className="row small muted">
          {r.sell_total != null && <span>Sell {usd(r.sell_total)}</span>}
          {r.gp_pct != null && <span>· {r.gp_pct}% GP</span>}
        </div>
      )}
      {link && (
        <a href={link} target="_blank" rel="noreferrer" className="small">
          Open in Meridian ↗
        </a>
      )}
    </div>
  )
}

export default function ApprovalQueue({ pending, onApproved, onToast }) {
  const [busyId, setBusyId] = useState(null)
  const [decided, setDecided] = useState([])

  async function decide(id, call) {
    setBusyId(id)
    try {
      const done = await call()
      setDecided((d) => [done, ...d])
      pending.refresh()
      return done
    } catch (e) {
      onToast(e.message, 'error')
      return null
    } finally {
      setBusyId(null)
    }
  }

  async function approve(action) {
    const done = await decide(action.action_id, () => api.approve(action.action_id))
    if (!done) return
    onApproved(done)
  }

  async function reject(action, reason) {
    const done = await decide(action.action_id, async () => ({
      ...action,
      ...(await api.reject(action.action_id, reason)),
      status: 'rejected',
      reject_reason: reason,
    }))
    if (done) onToast(`Rejected ${action.action_id}`, 'info')
  }

  const items = pending.data?.items || []

  return (
    <div>
      {pending.loading ? (
        <div className="stack">
          <div className="skeleton" />
          <div className="skeleton" />
        </div>
      ) : pending.error && !pending.data ? (
        <div className="empty">Could not load approvals: {pending.error}</div>
      ) : items.length === 0 ? (
        <div className="empty">Nothing waiting. Fill a return trip from the City tab or simulate an email.</div>
      ) : (
        <div className="stack">
          {items.map((a) => (
            <PendingCard
              key={a.action_id}
              action={a}
              busy={busyId === a.action_id}
              onApprove={approve}
              onReject={reject}
            />
          ))}
        </div>
      )}

      {decided.length > 0 && (
        <>
          <div className="section-title">Recently decided</div>
          <div className="stack">
            {decided.map((a) => <DecidedCard key={a.action_id} action={a} />)}
          </div>
        </>
      )}

      <div className="section-title">Agent activity</div>
      <AuditLog />
    </div>
  )
}
