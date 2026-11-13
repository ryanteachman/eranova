import { api } from '../api.js'
import usePoll from '../usePoll.js'

function clock(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
}

export default function AuditLog() {
  const audit = usePoll(() => api.getAudit(), 4000)

  if (audit.loading) {
    return (
      <div className="stack">
        {[0, 1, 2].map((i) => <div key={i} className="skeleton line" />)}
      </div>
    )
  }
  if (audit.error) return <p className="muted small">Could not load activity: {audit.error}</p>

  const items = (audit.data?.items || []).slice(0, 12)
  if (!items.length) return <p className="muted small">No activity yet.</p>

  return (
    <ul className="audit">
      {items.map((e, i) => (
        <li key={e.id ?? `${e.at}-${i}`}>
          <span>{clock(e.at)}</span>
          <span className={`actor-${e.actor}`}>{e.actor}</span>
          <b>{e.text ?? [e.event, e.detail].filter(Boolean).join(": ")}</b>
        </li>
      ))}
    </ul>
  )
}
