import { useState } from 'react'
import { api } from '../api.js'
import usePoll from '../usePoll.js'

const usd = (n) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
const lane = (l) => `${l.origin.city}, ${l.origin.state} → ${l.destination.city}, ${l.destination.state}`
const KIND = {
  carrier_ask: { label: 'Carrier ask', cls: 'warn' },
  carrier_counter: { label: 'Carrier counter', cls: 'warn' },
  carrier_accept: { label: 'Carrier would accept', cls: 'ok' },
  shipper_budget: { label: 'Shipper budget', cls: '' },
  competitor_quote: { label: 'Competitor price', cls: 'bad' },
}

function LaneCard({ l, signals }) {
  const [open, setOpen] = useState(false)
  const below = l.discount_pct > 0
  return (
    <div className="card stack" style={{ gap: 8 }}>
      <div className="row between">
        <span className="h3">{lane(l.lane)}</span>
        <span className={`badge eq-${l.equipment}`}>{l.equipment === 'R' ? 'Reefer' : 'Dry van'}</span>
      </div>
      <div className="price-compare num">
        <div>
          <small>Rate engine</small>
          <b>{usd(l.market_buy)}</b>
        </div>
        <div>
          <small>Said one-way</small>
          <b>{usd(l.one_way_buy)}</b>
        </div>
        <div className={below ? 'good' : 'bad'}>
          <small>Loop price (recommended)</small>
          <b>{usd(l.recommended_buy)}</b>
          <em>{below ? `${l.discount_pct}% under market` : `${Math.abs(l.discount_pct)}% over market`}</em>
        </div>
      </div>
      <p className="small muted" style={{ margin: 0 }}>{l.note}</p>
      <button className="btn small" onClick={() => setOpen((o) => !o)}>
        {open ? 'Hide' : 'Show'} the {signals.length} {signals.length === 1 ? 'conversation' : 'conversations'}
      </button>
      {open && (
        <ul className="signals">
          {signals.map((s) => (
            <li key={s.id}>
              <div className="row between wrap">
                <span className="row">
                  <span className="src">{s.source === 'call' ? '📞' : '✉️'}</span>
                  <b>{s.party_name}</b>
                  <span className={`badge ${KIND[s.kind]?.cls ?? ''}`}>{KIND[s.kind]?.label ?? s.kind}</span>
                </span>
                <b className="num">{usd(s.amount)}</b>
              </div>
              <q>{s.quote}</q>
              <span className="small muted">
                {s.ref} · {Math.round(s.confidence * 100)}% sure · used in {s.used_in}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function PriceSignals() {
  const { data, error, loading } = usePoll(() => api.getPriceSignals(), 10000)

  if (loading) return <div className="stack">{[0, 1, 2].map((i) => <div key={i} className="skeleton" />)}</div>
  if (error) return <div className="empty">Could not load price signals: {error}</div>

  const byId = Object.fromEntries(data.signals.map((s) => [s.id, s]))
  const s = data.summary
  return (
    <div className="stack">
      <div>
        <h2 className="h2">What carriers actually said</h2>
        <p className="muted" style={{ margin: '6px 0 0' }}>
          The brain pulls prices out of {s.emails} emails and {s.calls} call transcripts, then prices each loop from
          what carriers and shippers really said, not just the rate engine.
        </p>
      </div>
      <div className="row wrap" style={{ gap: 8 }}>
        <span className="badge ok">{s.signals} price signals</span>
        <span className="badge">{s.lanes} lanes priced</span>
        <span className="badge ok">Carriers take {s.avg_loop_discount_pct}% less when the loop brings them home</span>
      </div>
      {data.lanes.map((l) => (
        <LaneCard key={lane(l.lane)} l={l} signals={l.signals.map((id) => byId[id]).filter(Boolean)} />
      ))}
    </div>
  )
}
