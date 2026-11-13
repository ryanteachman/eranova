import { useEffect, useState } from 'react'
import { api } from '../api.js'
import './CarrierWeek.css'

const EQUIPMENT = { V: 'Dry van', R: 'Reefer', F: 'Flatbed' }

const money = (n, cents = false) =>
  n == null
    ? '—'
    : Number(n).toLocaleString('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: cents ? 2 : 0,
        maximumFractionDigits: cents ? 2 : 0,
      })

// "2026-11-16" -> local date (avoid the UTC shift of new Date('YYYY-MM-DD'))
function parseDay(s) {
  if (!s) return null
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s)
  if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? null : d
}

const shortDay = (s) => {
  const d = parseDay(s)
  if (!d) return ''
  return `${d.toLocaleDateString('en-US', { weekday: 'short' })} ${d.getMonth() + 1}/${d.getDate()}`
}

const weekdayLong = (s) => parseDay(s)?.toLocaleDateString('en-US', { weekday: 'short' }) || ''

function expiresText(iso) {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  const day = d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
  const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  return `${day}, ${time}`
}

const STATUS = {
  booked: { label: 'Booked', cls: 'ok' },
  covered: { label: 'Confirmed', cls: 'ok' },
  quoted: { label: 'Quoted', cls: 'info' },
  missing: { label: 'Being confirmed', cls: 'pending' },
  needs_carrier: { label: 'Being confirmed', cls: 'pending' },
}

const firstName = (name = '') => name.split(/\s+/)[0] || 'driver'
const city = (p) => (p ? `${p.city}, ${p.state}` : '')

function Ring({ pct }) {
  const r = 26
  const c = 2 * Math.PI * r
  const v = Math.max(0, Math.min(100, Number(pct) || 0))
  return (
    <svg className="cw-ring" viewBox="0 0 64 64" aria-label={`${v}% loaded`}>
      <defs>
        <linearGradient id="cwRingGrad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#4ade80" />
          <stop offset="100%" stopColor="#22d3ee" />
        </linearGradient>
      </defs>
      <circle cx="32" cy="32" r={r} className="cw-ring-track" />
      <circle
        cx="32"
        cy="32"
        r={r}
        className="cw-ring-fill"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - v / 100)}
      />
      <text x="32" y="36" textAnchor="middle" className="cw-ring-text">
        {v}%
      </text>
    </svg>
  )
}

function Timeline({ legs, home }) {
  return (
    <ol className="cw-timeline">
      {legs.map((l) =>
        l.kind === 'empty' ? (
          <li key={l.seq} className="cw-empty">
            <span className="cw-empty-line" />
            <span className="cw-empty-text">
              <b className="num">{Number(l.miles).toLocaleString()} mi</b> empty
              {l.note ? <span className="muted"> · {l.note}</span> : null}
            </span>
          </li>
        ) : (
          <li key={l.seq} className="cw-stop">
            <span className="cw-dot" />
            <div className="cw-stop-card">
              <div className="cw-stop-top">
                <span className="cw-lane">
                  {l.origin.city} <span className="cw-arrow">→</span> {l.destination.city}
                </span>
                <span className="cw-pay num">{money(l.pay)}</span>
              </div>
              <div className="cw-stop-meta num">
                {shortDay(l.pickup)}
                {l.deliver && l.deliver !== l.pickup ? ` – ${shortDay(l.deliver)}` : ''} ·{' '}
                {Number(l.miles).toLocaleString()} mi
              </div>
              <div className="cw-stop-bottom">
                <span className="cw-commodity">{l.commodity}</span>
                {STATUS[l.status] ? (
                  <span className={`cw-chip ${STATUS[l.status].cls}`}>{STATUS[l.status].label}</span>
                ) : null}
              </div>
            </div>
          </li>
        )
      )}
      <li className="cw-home">
        <span className="cw-home-icon" aria-hidden>
          <svg viewBox="0 0 24 24" width="14" height="14">
            <path d="M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" fill="currentColor" />
          </svg>
        </span>
        <span>
          <b>Home</b> <span className="muted">· {home}</span>
        </span>
      </li>
    </ol>
  )
}

export default function CarrierWeek({ weeks, selectedId, onSelect, onResponded, onToast }) {
  const [busy, setBusy] = useState(false)
  const [countering, setCountering] = useState(false)
  const [note, setNote] = useState('')

  const week = weeks?.find((w) => w.tour_id === selectedId) || weeks?.[0] || null

  useEffect(() => {
    setCountering(false)
    setNote('')
  }, [week?.tour_id])

  if (weeks == null) {
    return (
      <div className="cw-root">
        <div className="cw-stage">
          <div className="cw-phone">
            <div className="cw-screen cw-loading">
              <div className="skeleton line" style={{ width: '50%' }} />
              <div className="skeleton" style={{ height: 160 }} />
              <div className="skeleton" style={{ height: 70 }} />
              <div className="skeleton" />
              <div className="skeleton" />
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (!week) {
    return <div className="empty">No week offers yet. Book a loop to offer a carrier their week.</div>
  }

  const { carrier, totals = {}, standalone = {}, legs = [] } = week
  const homeCity = carrier.home?.city || 'home'
  const homeBy = `${weekdayLong(totals.home_by)} ${shortDay(totals.home_by).split(' ')[1] || ''}`.trim()
  const expires = expiresText(week.offer_expires)

  async function respond(decision) {
    if (busy) return
    setBusy(true)
    try {
      const updated = await api.respondWeek(week.tour_id, decision, decision === 'counter' ? note.trim() : undefined)
      if (decision === 'accept') {
        onToast?.(`Week accepted. ${carrier.name} is home by ${weekdayLong(totals.home_by)} ${shortDay(totals.home_by).split(' ')[1] || ''}.`, 'success')
      } else {
        onToast?.('Counter sent to broker', 'success')
      }
      setCountering(false)
      setNote('')
      onResponded?.(updated)
    } catch (e) {
      onToast?.(e.message || 'Could not send your response', 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="cw-root">
      <div className="cw-picker" role="tablist" aria-label="Carrier">
        {weeks.map((w) => (
          <button
            key={w.tour_id}
            role="tab"
            aria-selected={w.tour_id === week.tour_id}
            className={`cw-pick ${w.tour_id === week.tour_id ? 'on' : ''}`}
            onClick={() => onSelect?.(w.tour_id)}
          >
            <span className="cw-pick-name">{w.carrier.name}</span>
            <span className={`badge eq-${w.carrier.equipment}`}>{EQUIPMENT[w.carrier.equipment] || w.carrier.equipment}</span>
            {w.status !== 'offered' ? <span className={`cw-pick-dot ${w.status}`} title={w.status} /> : null}
          </button>
        ))}
      </div>

      <div className="cw-stage">
        <div className="cw-phone">
          <div className="cw-notch" />
          <div className="cw-screen" key={week.tour_id}>
            <div className="cw-status-bar num">
              <span>9:41</span>
              <span className="cw-status-icons" aria-hidden>
                <svg viewBox="0 0 18 12" width="17" height="11">
                  <rect x="0" y="8" width="3" height="4" rx="1" fill="currentColor" />
                  <rect x="5" y="5" width="3" height="7" rx="1" fill="currentColor" />
                  <rect x="10" y="2.5" width="3" height="9.5" rx="1" fill="currentColor" />
                  <rect x="15" y="0" width="3" height="12" rx="1" fill="currentColor" />
                </svg>
                <svg viewBox="0 0 26 12" width="24" height="11">
                  <rect x="0.5" y="0.5" width="22" height="11" rx="3" fill="none" stroke="currentColor" opacity="0.5" />
                  <rect x="2" y="2" width="16" height="8" rx="1.6" fill="currentColor" />
                  <rect x="23.5" y="4" width="2" height="4" rx="1" fill="currentColor" opacity="0.5" />
                </svg>
              </span>
            </div>

            <div className="cw-appbar">
              <span className="cw-logo">↺</span>
              <span>
                Return Trip <span className="cw-appbar-sub">· Driver</span>
              </span>
            </div>

            <div className="cw-scroll">
              <div className="cw-greeting">
                <h2>Hi {firstName(carrier.name)} 👋</h2>
                <p>
                  We planned your whole week{' '}
                  <span className="muted">· {EQUIPMENT[carrier.equipment] || carrier.equipment} from {homeCity}</span>
                </p>
              </div>

              <section className="cw-hero">
                <div className="cw-hero-head">
                  <div>
                    <div className="cw-eyebrow">Your week is full</div>
                    <div className="cw-total num">{money(totals.pay)}</div>
                    <div className="cw-total-sub num">
                      {Number(totals.loaded_miles || 0).toLocaleString()} loaded mi ·{' '}
                      {legs.filter((l) => l.kind !== 'empty').length} loads
                    </div>
                  </div>
                  <Ring pct={totals.loaded_pct} />
                </div>
                <div className="cw-hero-grid">
                  <div className="cw-kpi">
                    <span className="cw-kpi-label">Home by</span>
                    <b className="num">{homeBy}</b>
                  </div>
                  <div className="cw-kpi">
                    <span className="cw-kpi-label">Per mile</span>
                    <b className="num">{money(totals.per_mile, true)}</b>
                  </div>
                  <div className="cw-kpi">
                    <span className="cw-kpi-label">Idle days</span>
                    <b className="num">{totals.idle_days ?? 0}</b>
                  </div>
                </div>
                {totals.home_note ? <div className="cw-home-note">🏠 {totals.home_note}</div> : null}
              </section>

              <section className="cw-compare">
                <div className="cw-col without">
                  <span className="cw-col-label">Without the loop</span>
                  <b className="num">{money(standalone.pay)}</b>
                  <span className="num">{standalone.loaded_pct}% loaded</span>
                  <span className="num">
                    {standalone.idle_days} idle {standalone.idle_days === 1 ? 'day' : 'days'}
                  </span>
                </div>
                <div className="cw-vs">vs</div>
                <div className="cw-col with">
                  <span className="cw-col-label">With the loop</span>
                  <b className="num">{money(totals.pay)}</b>
                  <span className="num">{totals.loaded_pct}% loaded</span>
                  <span className="num">
                    {totals.idle_days ?? 0} idle {totals.idle_days === 1 ? 'day' : 'days'}
                  </span>
                </div>
              </section>
              {standalone.note ? <p className="cw-compare-note">{standalone.note}.</p> : null}

              <div className="cw-section-title">Your route</div>
              <Timeline legs={legs} home={homeBy ? `${homeCity}, ${homeBy}` : homeCity} />

              {expires && week.status === 'offered' ? (
                <div className="cw-expiry">
                  <span className="cw-pulse" /> Offer holds until <b className="num">{expires}</b>
                </div>
              ) : null}
            </div>

            <div className="cw-actions">
              {week.status === 'accepted' ? (
                <div className="cw-done ok">
                  <span className="cw-check">✓</span>
                  <div>
                    <b>Accepted — dispatcher notified</b>
                    <small>See you home {homeBy ? `by ${homeBy}` : 'soon'}.</small>
                  </div>
                </div>
              ) : week.status === 'countered' ? (
                <div className="cw-done countered">
                  <span className="cw-check">↩</span>
                  <div>
                    <b>Counter sent</b>
                    <small>{week.note ? `"${week.note}"` : 'The broker will get back to you.'}</small>
                  </div>
                </div>
              ) : countering ? (
                <form
                  className="cw-counter"
                  onSubmit={(e) => {
                    e.preventDefault()
                    respond('counter')
                  }}
                >
                  <input
                    autoFocus
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="e.g. Need $200 more on leg 2"
                    disabled={busy}
                  />
                  <div className="cw-counter-row">
                    <button type="button" className="cw-btn ghost" disabled={busy} onClick={() => setCountering(false)}>
                      Cancel
                    </button>
                    <button type="submit" className="cw-btn send" disabled={busy || !note.trim()}>
                      {busy ? 'Sending…' : 'Send'}
                    </button>
                  </div>
                </form>
              ) : (
                <div className="cw-action-row">
                  <button className="cw-btn accept" disabled={busy} onClick={() => respond('accept')}>
                    {busy ? 'Accepting…' : `Accept week · ${money(totals.pay)}`}
                  </button>
                  <button className="cw-btn outline" disabled={busy} onClick={() => setCountering(true)}>
                    Counter
                  </button>
                </div>
              )}
            </div>
            <div className="cw-home-bar" />
          </div>
        </div>
      </div>
    </div>
  )
}
