import { useMemo, useState } from 'react'
import { api, MERIDIAN_WEB_URL, meridianLink } from '../../api.js'
import usePoll from '../../usePoll.js'
import './ActivityPage.css'

// Full-page activity: the audit trail (left) next to Meridian itself (right).

const ACTOR = {
  agent: { label: 'Agent', tone: 'agent', group: 'agent' },
  email_pipeline: { label: 'Email', tone: 'email', group: 'email' },
  email: { label: 'Email', tone: 'email', group: 'email' },
  human: { label: 'Person', tone: 'person', group: 'people' },
  user: { label: 'Person', tone: 'person', group: 'people' },
  person: { label: 'Person', tone: 'person', group: 'people' },
  system: { label: 'System', tone: 'system', group: 'system' },
}
const actorOf = (a) => ACTOR[String(a || '').toLowerCase()] || { label: humanize(a || 'system'), tone: 'system', group: 'system' }

const FILTERS = [
  ['all', 'All'],
  ['writes', 'Changes in Meridian'],
  ['agent', 'Agent'],
  ['email', 'Email'],
  ['people', 'People'],
  ['system', 'System'],
]

const TOOL = {
  find_backhauls: 'Agent looked for return freight',
  network_overview: 'Agent checked the network',
  create_return_quote: 'Agent proposed a quote',
  send_reply: 'Agent drafted a reply',
  book_tour: 'Agent proposed booking a tour',
}
const EVENT = {
  email_processed: 'Email read and turned into actions',
  action_proposed: 'Action proposed for approval',
  sync: 'Synced Meridian data',
  classify: 'Classified shipments',
}

function humanize(key) {
  const s = String(key || '').replace(/[_-]+/g, ' ').trim()
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : ''
}
const clip = (s, n = 140) => (s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s)

// Turn one audit row into a sentence a person can read.
function sentence(row) {
  const event = row.event || row.kind || ''
  const detail = String(row.detail ?? row.text ?? '')
  if (event === 'tool_call') {
    const tool = (detail.match(/^\s*([a-zA-Z0-9_]+)/) || [])[1] || ''
    return TOOL[tool] || (tool ? `Agent used ${humanize(tool).toLowerCase()}` : 'Agent took a step')
  }
  if (event === 'agent_message') {
    const msg = detail.replace(/^\s*(user|human)\s*:\s*/i, '').trim()
    return msg ? `You asked the agent: “${clip(msg, 120)}”` : 'You asked the agent something'
  }
  if (TOOL[event]) return TOOL[event]
  if (EVENT[event]) return EVENT[event]
  if (!event && detail) return clip(detail)
  return humanize(event) || 'Activity'
}

// Path inside Meridian for an action result, e.g. '/quotes/7300182'.
function meridianPath(result) {
  if (!result) return null
  if (result.meridian_path) return result.meridian_path
  const url = meridianLink(result)
  if (url) {
    if (MERIDIAN_WEB_URL && url.startsWith(MERIDIAN_WEB_URL)) return url.slice(MERIDIAN_WEB_URL.length) || '/'
    try {
      const u = new URL(url)
      return u.pathname + u.search + u.hash
    } catch {
      return url.startsWith('/') ? url : null
    }
  }
  if (result.quote_id) return `/quotes/${result.quote_id}`
  return null
}
const isWrite = (a) => a.status === 'done' && a.result && (a.result.quote_id || a.result.meridian_url || a.result.meridian_path)

const money = (n) => (n == null || n === '' || isNaN(Number(n)) ? null : Number(n).toLocaleString('en-US', { style: 'currency', currency: 'USD' }))
const hhmm = (d) => d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
const dayKey = (d) => d.toDateString()
function dayLabel(d) {
  const today = new Date()
  const y = new Date(today)
  y.setDate(today.getDate() - 1)
  if (dayKey(d) === dayKey(today)) return 'Today'
  if (dayKey(d) === dayKey(y)) return 'Yesterday'
  return d.toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' })
}
function ago(d) {
  const s = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000))
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}
const toDate = (iso) => {
  const d = iso ? new Date(iso) : null
  return d && !isNaN(d) ? d : null
}

const place = (p) => (p ? [p.name, p.city && `${p.city}, ${p.state}`].filter(Boolean).join(' · ') : null)
const KIND = { create_return_quote: 'Quote created in Meridian', send_reply: 'Email reply sent', book_tour: 'Loop booked' }

// What exactly was approved, in words: the quote, the email that went out, or the loop.
function Approved({ action }) {
  const p = action.payload || {}
  const r = action.result || {}
  const fields = []
  const add = (k, v) => { if (v != null && v !== '' && !(Array.isArray(v) && !v.length)) fields.push([k, v]) }
  if (action.kind === 'create_return_quote' || r.quote_id) {
    add('Quote', r.quote_id && `#${r.quote_id}`)
    add('Customer', p.customer_id)
    add('From', place(p.origin))
    add('To', place(p.destination))
    add('Pickup', p.pickup_date)
    add('Freight', (p.freight_lines || []).map((f) => `${f.pieces ?? ''} ${String(f.package_type || '').toLowerCase()} · ${f.weight_lb?.toLocaleString() ?? '?'} lb · ${f.description}`).join('; '))
    add('Truck', [p.equipment_type, p.carrier_id, p.trailer_number && `trailer ${p.trailer_number}`].filter(Boolean).join(' · '))
    add('Miles', p.miles)
    add('Customer pays', money(r.sell_total))
    add('Carrier gets', money((p.buy_lines || []).reduce((t, l) => t + (l.amount || 0), 0) || null))
    add('Extras', (p.accessorials || []).join(', '))
  }
  if (action.kind === 'send_reply' || r.reply_id) add('Sent to', r.to)
  if (r.quote_ids?.length) add('Quotes', r.quote_ids.join(', '))
  return (
    <div className="ap-approved">
      <span className="ap-approved-kind">{KIND[action.kind] || humanize(action.kind)} · {action.title}</span>
      {fields.length > 0 && (
        <dl>
          {fields.map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
          ))}
        </dl>
      )}
      {r.body && <p className="ap-approved-body">{r.body}</p>}
      {action.reasoning && <p className="ap-approved-why"><b>Why the agent proposed it:</b> {action.reasoning}</p>}
    </div>
  )
}

function Row({ row, onOpen }) {
  const [open, setOpen] = useState(false)
  const a = actorOf(row.actor)
  if (row.action) {
    return (
      <div className={`ap-row ${row.tone || ''} clickable ${open ? 'open' : ''}`} onClick={() => setOpen((o) => !o)} role="button" tabIndex={0}
        onKeyDown={(e) => e.key === 'Enter' && setOpen((o) => !o)}>
        <span className="ap-time">{row.date ? hhmm(row.date) : ''}</span>
        <div className="ap-main">
          <div className="ap-line">
            <span className={`ap-badge ${a.tone}`}>{a.label}</span>
            <span className="ap-text">{row.text}</span>
          </div>
          <span className="ap-more">{open ? 'Hide' : 'See what was approved'}</span>
          {open && <Approved action={row.action} />}
          {row.path && (
            <button className="ap-open" onClick={(e) => { e.stopPropagation(); onOpen(row.path) }}>Open in Meridian ↗</button>
          )}
        </div>
      </div>
    )
  }
  return (
    <div className={`ap-row ${row.tone || ''}`}>
      <span className="ap-time">{row.date ? hhmm(row.date) : ''}</span>
      <div className="ap-main">
        <div className="ap-line">
          <span className={`ap-badge ${a.tone}`}>{a.label}</span>
          <span className="ap-text">{row.text}</span>
        </div>
        {row.path && (
          <button className="ap-open" onClick={() => onOpen(row.path)}>Open in Meridian ↗</button>
        )}
        {row.raw && (
          <>
            <button className="ap-more" onClick={() => setOpen((o) => !o)}>{open ? 'Hide details' : 'Details'}</button>
            {open && <pre className="ap-raw">{row.raw}</pre>}
          </>
        )}
      </div>
    </div>
  )
}

export default function ActivityPage({ onClose, focusPath }) {
  const audit = usePoll(() => api.getAudit(), 3000)
  const actions = usePoll(() => api.getActions(), 3000)
  const [filter, setFilter] = useState('all')
  const [picked, setPicked] = useState(focusPath || null)
  const [frameKey, setFrameKey] = useState(0)

  const actionItems = actions.data?.items || []

  // Real writes into Meridian, newest first.
  const writes = useMemo(
    () =>
      actionItems
        .filter(isWrite)
        .map((a) => ({ a, path: meridianPath(a.result), date: toDate(a.updated_at || a.created_at) }))
        .filter((w) => w.path)
        .sort((x, y) => (y.date?.getTime() || 0) - (x.date?.getTime() || 0)),
    [actionItems],
  )

  const rows = useMemo(() => {
    const known = new Set(actionItems.map((a) => a.action_id))
    const out = (audit.data?.items || []).filter((r) => {
      const id = (String(r.detail || '').match(/^(act_[a-z0-9]+)/) || [])[1]
      return !(r.event === 'action_approved' && id && known.has(id))
    }).map((r, i) => {
      const raw = String(r.detail ?? r.text ?? '').trim()
      const text = sentence(r)
      return {
        key: `au-${r.id || i}-${r.at}`,
        date: toDate(r.at),
        actor: r.actor,
        group: actorOf(r.actor).group,
        text,
        raw: raw && raw !== text ? raw : null,
      }
    })
    for (const a of actionItems) {
      if (a.status !== 'done' && a.status !== 'rejected' && a.status !== 'failed') continue
      const date = toDate(a.updated_at || a.created_at)
      const write = isWrite(a)
      const label = a.title || a.result?.summary || humanize(a.kind)
      out.push({
        key: `ac-${a.action_id}`,
        date,
        actor: 'human',
        group: 'people',
        write,
        tone: a.status === 'done' ? 'green' : 'red',
        text:
          a.status === 'done'
            ? write
              ? `Approved → written to Meridian: ${label}`
              : `Approved: ${label}`
            : a.status === 'rejected'
              ? `Rejected: ${a.title || humanize(a.kind)}`
              : `Failed: ${a.title || humanize(a.kind)}`,
        path: write ? meridianPath(a.result) : null,
        action: a,
      })
    }
    out.sort((x, y) => (y.date?.getTime() || 0) - (x.date?.getTime() || 0))
    return out
  }, [audit.data, actionItems])

  const shown = rows.filter((r) => (filter === 'all' ? true : filter === 'writes' ? r.write : r.group === filter))

  const today = dayKey(new Date())
  const stats = {
    writes: writes.length,
    waiting: actionItems.filter((a) => a.status === 'pending').length,
    steps: (audit.data?.items || []).filter((r) => actorOf(r.actor).group === 'agent' && toDate(r.at) && dayKey(toDate(r.at)) === today).length,
  }

  const path = picked || writes[0]?.path || '/'
  const src = MERIDIAN_WEB_URL ? MERIDIAN_WEB_URL + (path.startsWith('/') ? path : `/${path}`) : ''

  function openPath(p) {
    setPicked(p)
    setFrameKey((k) => k + 1) // reload even if the same path is picked again
  }

  let lastDay = null
  return (
    <div className="ap">
      <header className="ap-top">
        <div>
          <span className="ap-kicker">Everything the agent and people did</span>
          <h2>Activity</h2>
        </div>
        <nav className="ap-filters">
          {FILTERS.map(([id, label]) => (
            <button key={id} className={filter === id ? 'on' : ''} onClick={() => setFilter(id)}>{label}</button>
          ))}
        </nav>
        <button className="ap-close" onClick={onClose} aria-label="Close activity">✕</button>
      </header>

      <div className="ap-cols">
        {/* left · the timeline */}
        <section className="ap-left">
          <div className="ap-stats">
            <span className="ap-stat green"><b>{stats.writes}</b> {stats.writes === 1 ? 'change' : 'changes'} written to Meridian</span>
            <span className="ap-stat amber"><b>{stats.waiting}</b> waiting for approval</span>
            <span className="ap-stat blue"><b>{stats.steps}</b> agent {stats.steps === 1 ? 'step' : 'steps'} today</span>
          </div>
          <div className="ap-timeline">
            {audit.loading && [0, 1, 2, 3].map((i) => <div key={i} className="ap-skel" />)}
            {audit.error && !audit.data && <div className="ap-empty">Couldn’t load the activity log: {audit.error}</div>}
            {!audit.loading && shown.length === 0 && (
              <div className="ap-empty">
                {filter === 'writes' ? 'Nothing has been written to Meridian yet. Approve an action to see it here.' : 'No activity here yet.'}
              </div>
            )}
            {shown.map((r) => {
              const d = r.date ? dayKey(r.date) : 'unknown'
              const divider = d !== lastDay
              lastDay = d
              return (
                <div key={r.key}>
                  {divider && <div className="ap-day">{r.date ? dayLabel(r.date) : 'Earlier'}</div>}
                  <Row row={r} onOpen={openPath} />
                </div>
              )
            })}
          </div>
        </section>

        {/* right · Meridian itself */}
        <section className="ap-right">
          <div className="ap-bar">
            <div className="ap-bar-top">
              <span className="ap-live"><i /> Live in Meridian</span>
              <code className="ap-path">{path}</code>
              {src && (
                <a className="ap-ext" href={src} target="_blank" rel="noreferrer">Open in new tab ↗</a>
              )}
            </div>
            {writes.length > 0 && (
              <div className="ap-chips">
                {writes.slice(0, 12).map((w) => {
                  const id = w.a.result.quote_id
                  const total = money(w.a.result.sell_total)
                  return (
                    <button
                      key={w.a.action_id}
                      className={`ap-chip ${w.path === path ? 'on' : ''}`}
                      onClick={() => openPath(w.path)}
                      title={w.a.result.summary || w.a.title}
                    >
                      {id ? `Quote ${id}` : w.a.title || humanize(w.a.kind)}
                      {total && ` · ${total}`}
                      {w.date && ` · ${ago(w.date)}`}
                    </button>
                  )
                })}
              </div>
            )}
          </div>
          <div className="ap-frame">
            {src ? (
              <iframe key={`${frameKey}-${src}`} src={src} title="Meridian" />
            ) : (
              <div className="ap-empty">
                Meridian’s web address isn’t set, so it can’t be shown here.
                <br />
                <span className="ap-muted">Set VITE_MERIDIAN_WEB_URL to see Meridian live.</span>
              </div>
            )}
          </div>
          <p className="ap-note">This is Meridian itself. Changes appear here the moment they’re approved.</p>
        </section>
      </div>
    </div>
  )
}
