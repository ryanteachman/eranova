import { useState } from 'react'
import { api, meridianLink } from '../api.js'
import './TourBoard.css'

const EQUIPMENT = { V: 'Dry van', R: 'Reefer', F: 'Flatbed' }

const money = (n) => (n ?? 0).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
const place = (p) => `${p.city}, ${p.state}`
const sum = (tours, fn) => tours.reduce((total, t) => total + fn(t.totals), 0)

// "2026-11-14" -> "Nov 14" (noon so the timezone never shifts the day)
function shortDate(iso) {
  if (!iso) return ''
  return new Date(`${iso}T12:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// After a local approve the parent may not have refetched yet, so show the legs as booked.
function displayStatus(leg, result) {
  if (!result) return { status: leg.status, quoteId: leg.quote_id }
  if (leg.status === 'missing') return { status: 'quoted', quoteId: null }
  if (leg.status === 'needs_carrier') return { status: 'covered' }
  return { status: leg.status, quoteId: leg.quote_id }
}

export default function TourBoard({ tours, selectedId, onSelect, onBooked, onToast, pendingActionIds }) {
  const [busyId, setBusyId] = useState(null)
  const [results, setResults] = useState({}) // tour_id -> last approve result

  async function book(tour) {
    setBusyId(tour.tour_id)
    try {
      const action = await api.approve(tour.action_id)
      setResults((r) => ({ ...r, [tour.tour_id]: action.result }))
      onToast(action.result?.summary || `Tour ${tour.tour_id} booked`, 'success')
      onBooked(action)
    } catch (e) {
      onToast(e.message, 'error')
    } finally {
      setBusyId(null)
    }
  }

  if (tours === null) {
    return (
      <div className="stack">
        <div className="skeleton" style={{ height: 72 }} />
        <div className="skeleton" style={{ height: 420 }} />
        <div className="skeleton" style={{ height: 420 }} />
      </div>
    )
  }

  if (tours.length === 0) {
    return <div className="empty">No tours yet. The brain hasn't found a loop that closes.</div>
  }

  return (
    <div className="stack tour-board">
      <BoardHeader tours={tours} />
      {tours.map((t) => (
        <TourCard
          key={t.tour_id}
          tour={t}
          selected={t.tour_id === selectedId}
          pending={!pendingActionIds || pendingActionIds.includes(t.action_id)}
          result={results[t.tour_id]}
          busy={busyId === t.tour_id}
          onSelect={() => onSelect(t.tour_id)}
          onBook={() => book(t)}
        />
      ))}
    </div>
  )
}

function BoardHeader({ tours }) {
  const profit = sum(tours, (x) => x.profit_unlocked)
  const loaded = Math.round(sum(tours, (x) => x.loaded_pct) / tours.length)
  const baseline = Math.round(sum(tours, (x) => x.standalone_loaded_pct) / tours.length)
  const avoided = sum(tours, (x) => x.standalone_empty_miles - x.empty_miles)

  return (
    <div className="tb-header">
      <div className="row between wrap">
        <h2 className="h2">Tours the brain built</h2>
        <span className="muted small">{tours.length} loops</span>
      </div>
      <div className="tb-stats">
        <div className="tb-stat profit">
          <b className="num">+{money(profit)}</b>
          <small>vs booking one by one</small>
        </div>
        <div className="tb-stat">
          <b className="num">{loaded}%</b>
          <small>loaded vs {baseline}%</small>
        </div>
        <div className="tb-stat">
          <b className="num">{avoided.toLocaleString('en-US')} mi</b>
          <small>empty miles avoided</small>
        </div>
      </div>
    </div>
  )
}

function TourCard({ tour, selected, pending, result, busy, onSelect, onBook }) {
  const booked = Boolean(result) || (tour.status !== 'proposed' && !pending)
  const canBook = !booked && tour.status === 'proposed' && pending
  const failed = tour.decisions.filter((d) => !d.passed).length
  const confidence = Math.round(tour.confidence * 100)

  // quote ids come back in leg order, so hand them out to the missing legs one by one
  const quoteIds = [...(result?.quote_ids || [])]
  const link = meridianLink(result)

  return (
    <div
      className={`card tour ${selected ? 'selected' : ''} ${booked ? 'is-booked' : ''}`}
      style={{ '--tour': tour.color || 'var(--accent)' }}
      onClick={onSelect}
    >
      <div className="row between tb-top">
        <div className="stack" style={{ gap: 4 }}>
          <h3 className="h3 tb-name">
            <i className="tb-swatch" />
            {tour.name}
          </h3>
          <div className="row wrap small muted">
            <span>{tour.carrier.name}</span>
            <span className={`badge eq-${tour.equipment}`}>{EQUIPMENT[tour.equipment] || tour.equipment}</span>
            <span>
              {shortDate(tour.window.start)} – {shortDate(tour.window.end)}
            </span>
          </div>
        </div>
        <span className={`tb-pill ${booked ? 'booked' : 'proposed'}`}>{booked ? 'Booked' : 'Waiting for you'}</span>
      </div>

      <blockquote className="tb-headline">{tour.headline}</blockquote>

      <div className="section-title">The loop</div>
      <ol className="tb-legs">
        {tour.legs.map((leg) => {
          const shown = displayStatus(leg, result)
          const quoteId = shown.status === 'quoted' && !shown.quoteId ? quoteIds.shift() : shown.quoteId
          return leg.kind === 'empty' ? (
            <EmptyLeg key={leg.seq} leg={leg} />
          ) : (
            <LoadedLeg key={leg.seq} leg={leg} status={shown.status} quoteId={quoteId} carrier={tour.carrier.name} />
          )
        })}
      </ol>

      <MoneyCompare totals={tour.totals} />

      <details className="tb-decisions" onClick={(e) => e.stopPropagation()}>
        <summary>
          How the brain decided · {tour.decisions.length - failed} passed
          {failed > 0 && <span className="tb-fail-count">, {failed} rejected or flagged</span>}
        </summary>
        <ul className="reasons">
          {tour.decisions.map((d) => (
            <li key={d.check} className={d.passed ? '' : 'failed'}>
              <span className={d.passed ? 'pass' : 'fail'}>{d.passed ? '✓' : '✗'}</span>
              {d.text}
            </li>
          ))}
        </ul>
      </details>

      <div className="row between wrap tb-footer">
        <div className="row small muted">
          Confidence
          <div className="conf">
            <i style={{ width: `${confidence}%` }} />
          </div>
          <span className="num">{confidence}%</span>
        </div>

        {canBook && (
          <button
            className="btn success tb-book"
            disabled={busy}
            onClick={(e) => {
              e.stopPropagation()
              onBook()
            }}
          >
            {busy ? 'Booking…' : 'Book this loop'}
          </button>
        )}
        {!booked && !canBook && <span className="muted small">Approval is no longer in the queue</span>}
      </div>

      {booked && (
        <div className="tb-result small">
          <span className="tb-check">✓</span>
          <span>
            {result
              ? `${result.quote_ids?.length || 0} ${result.quote_ids?.length === 1 ? 'quote' : 'quotes'} created${
                  result.quote_ids?.length ? ` (#${result.quote_ids.join(', #')})` : ''
                }, week offered to ${tour.carrier.name}`
              : `Booked. Week offered to ${tour.carrier.name}`}
          </span>
          {link && (
            <a href={link} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
              Open in Meridian ↗
            </a>
          )}
        </div>
      )}
    </div>
  )
}

const LEG_LABEL = {
  booked: 'Booked',
  covered: 'Covered',
  needs_carrier: 'Needs carrier',
  missing: 'Missing leg · found by agent',
  quoted: 'Quoted',
}

function LoadedLeg({ leg, status, quoteId, carrier }) {
  let label = LEG_LABEL[status] || status
  if (status === 'needs_carrier') label = `Needs carrier → ${carrier.split(' ')[0]}`
  if (status === 'quoted' && quoteId) label = `Quoted #${quoteId}`
  const saved = leg.standalone_buy - leg.tour_buy

  return (
    <li className={`tb-leg st-${status}`}>
      <span className="tb-dot" />
      <div className="tb-leg-body">
        <div className="row between wrap">
          <b className="tb-lane">
            {place(leg.origin)} → {place(leg.destination)}
          </b>
          <span className="tb-leg-tag">{label}</span>
        </div>
        <div className="small muted">
          <span className="num">{leg.miles.toLocaleString('en-US')} mi</span> · {shortDate(leg.pickup)} →{' '}
          {shortDate(leg.deliver)} · {leg.customer} · {leg.commodity}
        </div>
        {status === 'missing' && leg.source && <div className="tb-source small">{leg.source}</div>}
        <div className="tb-leg-money small num">
          <span>
            sell <b>{money(leg.sell)}</b>
          </span>
          <span>
            buy tour <b>{money(leg.tour_buy)}</b>
            {saved > 0 && <s className="muted"> solo {money(leg.standalone_buy)}</s>}
          </span>
          <span className={leg.tour_gp_pct > leg.standalone_gp_pct ? 'tb-up' : 'muted'}>
            {leg.tour_gp_pct}% GP
            {leg.tour_gp_pct !== leg.standalone_gp_pct && <span className="muted"> vs {leg.standalone_gp_pct}% solo</span>}
          </span>
        </div>
      </div>
    </li>
  )
}

function EmptyLeg({ leg }) {
  return (
    <li className="tb-leg tb-empty">
      <span className="tb-dot" />
      <div className="tb-leg-body small muted">
        <span className="num">{leg.miles} mi empty</span> · {leg.note || `${place(leg.origin)} → ${place(leg.destination)}`}
      </div>
    </li>
  )
}

function MoneyCompare({ totals }) {
  const max = Math.max(totals.tour_gp, totals.standalone_gp) || 1
  return (
    <div className="tb-money">
      <div className="tb-money-grid">
        <div className="tb-block solo">
          <small>Booked one by one</small>
          <b className="num">{money(totals.standalone_gp)}</b>
          <div className="tb-bar">
            <i style={{ width: `${(totals.standalone_gp / max) * 100}%` }} />
          </div>
          <span className="small muted num">
            {totals.standalone_gp_pct}% GP · {totals.standalone_loaded_pct}% loaded
          </span>
        </div>
        <div className="tb-block loop">
          <small>As a loop</small>
          <b className="num">{money(totals.tour_gp)}</b>
          <div className="tb-bar">
            <i style={{ width: `${(totals.tour_gp / max) * 100}%` }} />
          </div>
          <span className="small muted num">
            {totals.tour_gp_pct}% GP · {totals.loaded_pct}% loaded
          </span>
        </div>
      </div>
      <div className="row between wrap">
        <span className="tb-delta num">+{money(totals.profit_unlocked)} profit unlocked</span>
        <span className="small muted num">Carrier earns {money(totals.carrier_pay_per_mile)}/mi</span>
      </div>
    </div>
  )
}
