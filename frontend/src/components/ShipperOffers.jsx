import { useMemo, useState } from 'react'
import { api } from '../api.js'
import './ShipperOffers.css'

const money = (n) =>
  Number(n || 0).toLocaleString('en-US', { style: 'currency', currency: 'USD' })

const moneyRound = (n) =>
  Number(n || 0).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

// "2026-11-19" -> "Thu 11/19" (parsed as a local date so it never shifts a day)
function shortDate(iso) {
  if (!iso) return ''
  const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number)
  if (!y || !m || !d) return String(iso)
  const dt = new Date(y, m - 1, d)
  const dow = dt.toLocaleDateString('en-US', { weekday: 'short' })
  return `${dow} ${m}/${d}`
}

const place = (p) => (p ? `${p.city}, ${p.state}` : '?')

const KIND = {
  backhaul_rate: { label: 'Truck already nearby', cls: 'kind-backhaul', icon: '🚚' },
  flex_date: { label: 'Flexible date', cls: 'kind-flex', icon: '📅' },
}

export default function ShipperOffers({
  offers,
  selectedShipper = null,
  onSelectShipper,
  onFocus,
  onResponded,
  onToast,
}) {
  const [busy, setBusy] = useState({}) // offer_id -> 'accept' | 'decline'
  const [local, setLocal] = useState({}) // offer_id -> updated offer from the API
  const [focusedId, setFocusedId] = useState(null)

  const merged = useMemo(
    () => (offers || []).map((o) => local[o.offer_id] || o),
    [offers, local],
  )

  const shippers = useMemo(() => {
    const seen = new Map()
    merged.forEach((o) => {
      if (o.shipper && !seen.has(o.shipper.id)) seen.set(o.shipper.id, o.shipper)
    })
    return [...seen.values()]
  }, [merged])

  const visible = useMemo(
    () => (selectedShipper ? merged.filter((o) => o.shipper?.id === selectedShipper) : merged),
    [merged, selectedShipper],
  )

  const stats = useMemo(() => {
    const live = visible.filter((o) => o.status === 'open' || o.status === 'accepted')
    const saved = live.reduce((s, o) => s + (Number(o.savings) || 0), 0)
    const accepted = visible.filter((o) => o.status === 'accepted')
    const locked = accepted.reduce((s, o) => s + (Number(o.savings) || 0), 0)
    const open = visible.filter((o) => o.status === 'open').length
    return { saved, locked, open, accepted: accepted.length }
  }, [visible])

  const focus = (o) => {
    setFocusedId(o.offer_id)
    onFocus?.(o)
  }

  async function respond(o, decision) {
    if (busy[o.offer_id]) return
    setBusy((b) => ({ ...b, [o.offer_id]: decision }))
    try {
      const updated = (await api.respondOffer(o.offer_id, decision)) || {
        ...o,
        status: decision === 'accept' ? 'accepted' : 'declined',
      }
      setLocal((l) => ({ ...l, [o.offer_id]: updated }))
      if (decision === 'accept') {
        onToast?.(`${o.shipper.name} accepted. The loop closes.`, 'success')
      } else {
        onToast?.(`${o.shipper.name} declined ${o.offer_id}. The brain will look for another fit.`, 'info')
      }
      onResponded?.(updated)
    } catch (err) {
      onToast?.(err?.message || 'Could not send the response.', 'error')
    } finally {
      setBusy((b) => {
        const next = { ...b }
        delete next[o.offer_id]
        return next
      })
    }
  }

  const loading = offers == null

  return (
    <div className="so">
      <header className="so-head">
        <div className="row between so-title-row">
          <div>
            <h2 className="h2">Offers for shippers</h2>
            <div className="muted small">
              Ship on trucks that are already coming your way, below market.
            </div>
          </div>
          {!loading && (
            <div className="so-stat">
              <b className="num">{moneyRound(stats.saved)}</b>
              <small>saved this week</small>
            </div>
          )}
        </div>

        <div className="so-pills" role="tablist" aria-label="Choose a company">
          <button
            type="button"
            role="tab"
            aria-selected={!selectedShipper}
            className={`so-pill ${!selectedShipper ? 'on' : ''}`}
            onClick={() => onSelectShipper?.(null)}
          >
            All
            {!loading && <span className="so-pill-count num">{merged.length}</span>}
          </button>
          {shippers.map((s) => (
            <button
              key={s.id}
              type="button"
              role="tab"
              aria-selected={selectedShipper === s.id}
              className={`so-pill ${selectedShipper === s.id ? 'on' : ''}`}
              onClick={() => onSelectShipper?.(s.id)}
            >
              <span className="so-pill-name">{s.name}</span>
              {s.type && <span className="so-pill-type">· {s.type}</span>}
            </button>
          ))}
          {loading && (
            <>
              <span className="skeleton line so-pill-skel" />
              <span className="skeleton line so-pill-skel" />
            </>
          )}
        </div>

        {!loading && visible.length > 0 && (
          <div className="so-summary small num">
            <span>
              <i className="dot open" /> {stats.open} open
            </span>
            <span>
              <i className="dot accepted" /> {stats.accepted} accepted
            </span>
            {stats.locked > 0 && (
              <span className="so-locked">{money(stats.locked)} locked in</span>
            )}
          </div>
        )}
      </header>

      {loading ? (
        <div className="stack">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card so-skel-card">
              <div className="skeleton line" style={{ width: '38%' }} />
              <div className="skeleton line" style={{ width: '72%', height: 20 }} />
              <div className="skeleton line" style={{ width: '90%' }} />
              <div className="skeleton" style={{ height: 64 }} />
            </div>
          ))}
        </div>
      ) : visible.length === 0 ? (
        <div className="empty">
          No offers right now.
          <br />
          <span className="small">When a truck is about to drive home empty near you, it shows up here.</span>
        </div>
      ) : (
        <div className="stack">
          {visible.map((o) => (
            <OfferCard
              key={o.offer_id}
              offer={o}
              busy={busy[o.offer_id]}
              focused={focusedId === o.offer_id}
              onFocus={() => focus(o)}
              onAccept={() => respond(o, 'accept')}
              onDecline={() => respond(o, 'decline')}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function OfferCard({ offer: o, busy, focused, onFocus, onAccept, onDecline }) {
  const kind = KIND[o.kind] || { label: o.kind, cls: '', icon: '•' }
  const pct = o.market_price ? Math.round((Number(o.savings) / Number(o.market_price)) * 100) : null
  const isOpen = o.status === 'open'
  const isAccepted = o.status === 'accepted'
  const isDeclined = o.status === 'declined'

  return (
    <article
      className={`card so-card ${kind.cls} status-${o.status} ${focused ? 'focused' : ''}`}
      tabIndex={0}
      onMouseEnter={onFocus}
      onClick={onFocus}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && e.target === e.currentTarget) onFocus()
      }}
    >
      <div className="row between so-card-top">
        <div className="row wrap">
          <span className={`badge so-kind ${kind.cls}`}>
            <span aria-hidden="true">{kind.icon}</span> {kind.label}
          </span>
          <span className="small muted">{o.shipper?.name}</span>
        </div>
        <span className="small muted num">{o.offer_id}</span>
      </div>

      <div className="so-body">
        <div className="so-main">
          <h3 className="so-title">{o.title}</h3>
          {o.detail && <p className="so-detail">{o.detail}</p>}

          <div className="so-route">
            <span className="so-city">{place(o.lane?.origin)}</span>
            <span className="so-arrow" aria-hidden="true">
              <i />→
            </span>
            <span className="so-city">{place(o.lane?.destination)}</span>
          </div>

          <div className="so-date num">
            {o.kind === 'flex_date' && o.original_date ? (
              <>
                <s className="so-date-old">{shortDate(o.original_date)}</s>
                <span className="so-date-arrow" aria-hidden="true">→</span>
                <span className="so-date-new">{shortDate(o.date)}</span>
              </>
            ) : (
              <span className="so-date-plain">{shortDate(o.date)}</span>
            )}
          </div>
        </div>

        <div className="so-price">
          <div className="so-price-now num">{money(o.price)}</div>
          <s className="so-price-market num">{money(o.market_price)} market</s>
          <div className="so-save num">
            Save {money(o.savings)}
            {pct != null && <span> · {pct}% under market</span>}
          </div>
        </div>
      </div>

      {o.reasons?.length > 0 && (
        <ul className="so-reasons">
          {o.reasons.map((r, i) => (
            <li key={i}>
              <span className="so-check" aria-hidden="true">✓</span>
              {r}
            </li>
          ))}
        </ul>
      )}

      <footer className="so-foot">
        {isOpen && (
          <div className="row">
            <button
              type="button"
              className="btn success"
              disabled={!!busy}
              onClick={(e) => {
                e.stopPropagation()
                onAccept()
              }}
            >
              {busy === 'accept' ? <Spinner label="Booking" /> : `Accept · ${money(o.price)}`}
            </button>
            <button
              type="button"
              className="btn so-decline"
              disabled={!!busy}
              onClick={(e) => {
                e.stopPropagation()
                onDecline()
              }}
            >
              {busy === 'decline' ? <Spinner label="Declining" /> : 'Decline'}
            </button>
          </div>
        )}
        {isAccepted && (
          <div className="so-accepted">
            <span className="so-accepted-mark">✓</span>
            Accepted ✓ — booked into tour {o.tour_id || '—'}
          </div>
        )}
        {isDeclined && <div className="so-declined small">Declined. This offer is closed.</div>}
        {!isOpen && !isAccepted && !isDeclined && (
          <div className="so-declined small">Status: {o.status}</div>
        )}
      </footer>
    </article>
  )
}

function Spinner({ label }) {
  return (
    <span className="so-spin-wrap">
      <span className="so-spin" aria-hidden="true" />
      {label}…
    </span>
  )
}
