import { useState } from 'react'
import { api, meridianLink } from '../../api.js'

const usd = (n) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
const usd0 = (n) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const weekday = (d) => new Date(`${d}T12:00:00`).toLocaleDateString('en-US', { weekday: 'short' })
const CHIP = { booked: 'Booked', covered: 'Covered', missing: 'Found by brain', needs_carrier: 'Needs carrier', quoted: 'Quoted' }

function Strip({ tour }) {
  const nodes = []
  tour.legs.forEach((l, i) => {
    if (i === 0) nodes.push(<Stop key="start" name={l.origin.city} />)
    nodes.push(
      l.kind === 'empty' ? (
        <div key={`s${l.seq}`} className="seg empty">
          <div className="line" />
          <span className="lbl">{l.miles} mi empty</span>
        </div>
      ) : (
        <div key={`s${l.seq}`} className={`seg ${l.status}`}>
          <div className="line" />
          <span className={`chip ${l.status}`}>{CHIP[l.status] ?? l.status}</span>
          <span className="lbl">
            <b>{l.customer.replace(/ - .*/, '')}</b>
            <br />
            {l.miles} mi · {weekday(l.pickup)}
          </span>
        </div>
      ),
    )
    const home = i === tour.legs.length - 1
    nodes.push(<Stop key={`e${l.seq}`} name={l.destination.city} home={home} />)
  })
  return <div className="strip">{nodes}</div>
}

function Stop({ name, home }) {
  return (
    <div className="stop">
      <span className={`pin ${home ? 'home' : ''}`} />
      <span className="name">{home ? `${name} (home)` : name}</span>
    </div>
  )
}

function Why({ tour, priceLanes }) {
  const evidence = (priceLanes ?? []).filter((pl) =>
    tour.legs.some((l) => l.kind !== 'empty' && l.origin.city === pl.lane.origin.city && l.destination.city === pl.lane.destination.city),
  )
  return (
    <div className="why">
      <div>
        <h4>What the brain checked</h4>
        <ul>
          {tour.decisions.map((d, i) => (
            <li key={i}>
              <span className={d.passed ? 'ok' : 'no'}>{d.passed ? '✓' : '✗'}</span>
              <span>{d.text}</span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h4>Price evidence from calls and emails</h4>
        <div className="stack" style={{ gap: 8 }}>
          {evidence.length === 0 && <span className="small muted">No conversations on these lanes yet; priced from the rate engine.</span>}
          {evidence.map((pl) => (
            <div key={pl.lane.origin.city + pl.lane.destination.city} className="evidence">
              <b>
                {pl.lane.origin.city} → {pl.lane.destination.city}: {usd(pl.recommended_buy)}
              </b>
              <span>{pl.note}</span>
              {pl.quotes?.slice(0, 1).map((s) => (
                <span key={s.id}>
                  <q>{s.quote}</q> <span className="src">· {s.party_name}, {s.source}</span>
                </span>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export { Why }

export default function TourDetail({ tour, pendingActionIds, priceLanes, onBooked, onToast }) {
  const [busy, setBusy] = useState(false)
  const [why, setWhy] = useState(false)
  const [result, setResult] = useState(null)
  if (!tour) return null

  const t = tour.totals
  const booked = tour.status === 'booked'
  const canBook = !booked && pendingActionIds.includes(tour.action_id)
  const link = meridianLink(result)

  async function book() {
    setBusy(true)
    try {
      const action = await api.approve(tour.action_id)
      setResult(action.result)
      onToast(action.result?.summary ?? `Tour ${tour.tour_id} booked`, 'success')
      onBooked(action)
    } catch (e) {
      onToast(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="scroll">
      <div className="detail-head">
        <span className="dot" style={{ background: tour.color, width: 14, height: 14 }} />
        <div>
          <h2>{tour.name}</h2>
          <span className="sub">
            {tour.carrier.name} · {tour.window.start.slice(5).replace('-', '/')} to {tour.window.home_by.slice(5).replace('-', '/')} ·{' '}
            {Math.round(tour.confidence * 100)}% confident
          </span>
        </div>
        <span className="grow" />
        {link && <a className="ghost" href={link} target="_blank" rel="noreferrer">Open in Meridian ↗</a>}
        {booked ? (
          <button className="cta done" disabled>Booked ✓</button>
        ) : (
          <button className="cta" onClick={book} disabled={busy || !canBook}>
            {busy ? 'Booking…' : `Book this loop · +${usd0(t.profit_unlocked)}`}
          </button>
        )}
      </div>

      <Strip tour={tour} />

      <div className="stats">
        <div className="stat green">
          <small>Extra profit for you</small>
          <b>+{usd(t.profit_unlocked)}</b>
          <span>vs booking each load alone</span>
        </div>
        <div className="stat">
          <small>Truck loaded</small>
          <b>{t.loaded_pct}%</b>
          <span>instead of 50%</span>
        </div>
        <div className="stat">
          <small>Your margin</small>
          <b>{t.tour_gp_pct}%</b>
          <span>instead of {t.standalone_gp_pct}%</span>
        </div>
        <div className="stat">
          <small>Carrier earns</small>
          <b>${t.carrier_pay_per_mile}/mi</b>
          <span>home {weekday(tour.window.home_by)}, 0 idle days</span>
        </div>
      </div>

      <button className="why-toggle" onClick={() => setWhy((w) => !w)}>
        {why ? 'Hide' : 'Why'} this loop {why ? '↑' : '→'}
      </button>
      {why && <Why tour={tour} priceLanes={priceLanes} />}
    </div>
  )
}
