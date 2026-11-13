import { useMemo, useState } from 'react'
import { api } from '../../api.js'
import usePoll from '../../usePoll.js'
import WeekChart from './WeekChart.jsx'
import './Reports.css'

// Weekly reports for the broker, each carrier and each manufacturer, plus what the brain has
// learned. Every number comes from Meridian's own history (frontend/tools/learn.py) or from
// loops booked in the app.

const usd0 = (n) => (n ?? 0).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const fmtDay = (d) => new Date(`${d}T12:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })

function Delta({ now, before, good = 'up', unit = '' }) {
  if (now == null || before == null || before === 0) return null
  const diff = now - before
  const up = diff >= 0
  const better = good === 'up' ? up : !up
  return (
    <span className={`rp-delta ${better ? 'good' : 'bad'}`}>
      {up ? '▲' : '▼'} {Math.abs(Math.round(diff)).toLocaleString()}
      {unit} vs last week
    </span>
  )
}

function Tile({ label, value, children }) {
  return (
    <div className="rp-tile">
      <small>{label}</small>
      <b>{value}</b>
      {children}
    </div>
  )
}

function Rules({ learned }) {
  return (
    <section className="rp-section">
      <h3>What the brain learned from your history</h3>
      <p className="rp-sub">
        From {learned.loads_learned_from} delivered loads. These rules feed straight back into how it builds loops, and update every
        time a load closes.
      </p>
      <ul className="rp-rules">
        {learned.rules.map((r, i) => (
          <li key={i}>
            <span className={`rp-area ${r.area}`}>{{ timing: 'Timing', carrier: 'Carrier', lead_time: 'Lead time' }[r.area]}</span>
            <div>
              <b>{r.text}</b>
              <span>{r.evidence}</span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function BrokerReport({ rep, learned, impact }) {
  const t = rep.broker.this
  const p = rep.broker.prev
  const net = rep.broker.network
  const series = rep.series.filter((d) => d.week <= rep.week).slice(-16) // only weeks that have happened
  return (
    <>
      <div className="rp-tiles">
        <Tile label="Coming in (customers)" value={usd0(t.revenue)}><Delta now={t.revenue} before={p.revenue} /></Tile>
        <Tile label="Going out (carriers)" value={usd0(t.carrier_cost)}><Delta now={t.carrier_cost} before={p.carrier_cost} good="down" /></Tile>
        <Tile label="Your margin" value={usd0(t.margin)}><Delta now={t.margin} before={p.margin} /></Tile>
        <Tile label="On time" value={t.on_time_pct == null ? '—' : `${t.on_time_pct}%`}><Delta now={t.on_time_pct} before={p.on_time_pct} unit=" pts" /></Tile>
      </div>

      <section className="rp-section rp-impact">
        <h3>Return Trip's own results</h3>
        <div className="rp-tiles">
          <Tile label="Loops booked in the app" value={impact.loops} />
          <Tile label="Empty miles saved" value={`${impact.miles.toLocaleString()} mi`} />
          <Tile label="Empty-driving cost avoided" value={usd0(impact.saved)} />
          <Tile label="Margin on booked loops" value={usd0(impact.margin)} />
        </div>
        <p className="rp-sub">
          The goal it's working on: Meridian drove {net.one_by_one.empty_miles.toLocaleString()} empty miles since {fmtDay(net.period.from)}.{' '}
          {net.return_lanes.share_of_empty}% of that is on {net.return_lanes.lanes} return trips worth {usd0(net.return_lanes.freight_value_usd)} at market rates.
        </p>
      </section>

      <section className="rp-section rp-charts">
        <WeekChart title="Margin per week" data={series} value={(d) => d.margin} format={usd0} color="#16a34a" />
        <WeekChart title="On-time deliveries per week" data={series} value={(d) => d.on_time_pct} format={(v) => `${v}%`} kind="line" color="#2541ff" />
        <WeekChart title="Loads per week" data={series} value={(d) => d.loads} format={(v) => `${v} loads`} color="#111827" />
        <WeekChart title="Empty miles per week (trucks driving home with nothing)" data={series} value={(d) => d.empty_miles} format={(v) => `${v.toLocaleString()} mi`} color="#d97706" />
      </section>

      <Rules learned={learned} />
    </>
  )
}

function CarrierReport({ rep, learned, id }) {
  const c = rep.carriers[id]
  const stats = learned.carriers.find((x) => x.carrier_id === id)
  const rank = learned.carriers.findIndex((x) => x.carrier_id === id) + 1
  const fastest = learned.lanes.filter((l) => l.fastest_carrier === c.name)
  return (
    <>
      <div className="rp-tiles">
        <Tile label="Loads this week" value={c.this.loads} />
        <Tile label="Paid to you this week" value={usd0(c.this.carrier_cost)} />
        <Tile label="On time (all loads)" value={stats?.on_time_pct == null ? '—' : `${stats.on_time_pct}%`} />
        <Tile label="Billable detention (all loads)" value={`${c.all.detention_hours} h`} />
      </div>
      <section className="rp-section">
        <h3>How you compare</h3>
        <ul className="rp-list">
          <li><b>#{rank} of {learned.carriers.length}</b><span>carriers on Meridian by on-time rate</span></li>
          <li><b>{c.all.loads} loads · {c.all.miles.toLocaleString()} mi</b><span>hauled for Meridian since January, {usd0(c.all.carrier_cost)} paid</span></li>
          <li><b>{c.all.avg_dwell_h ?? '—'} h</b><span>average wait at docks (detention starts after 2 h)</span></li>
          {fastest.map((l) => (
            <li key={l.lane}><b>Fastest on {l.lane}</b><span>{l.fastest_h} h door to door vs {l.avg_transit_h} h average. The brain offers you this lane first.</span></li>
          ))}
        </ul>
      </section>
    </>
  )
}

function ShipperReport({ rep, learned, id }) {
  const s = rep.shippers[id]
  const docks = learned.facilities.filter((f) => f.name && s.name && f.name.split(' - ')[0] === s.name.split(' - ')[0])
  return (
    <>
      <div className="rp-tiles">
        <Tile label="Shipments this week" value={s.this.loads} />
        <Tile label="Spent this week" value={usd0(s.this.revenue)} />
        <Tile label="On time (all shipments)" value={s.all.on_time_pct == null ? '—' : `${s.all.on_time_pct}%`} />
        <Tile label="Booked ahead of pickup" value={s.avg_lead_days == null ? '—' : `${s.avg_lead_days} days`} />
      </div>
      <section className="rp-section">
        <h3>Your freight with Meridian</h3>
        <ul className="rp-list">
          <li><b>{s.all.loads} shipments · {usd0(s.all.revenue)}</b><span>since January</span></li>
          <li><b>{s.all.late_loads} late</b><span>{s.all.late_loads ? 'deliveries that missed their window' : 'every delivery made its window'}</span></li>
          <li><b>{s.all.avg_dwell_h ?? '—'} h</b><span>average time trucks wait at your docks and your receivers'</span></li>
          {docks.map((f) => (
            <li key={f.facility_id}><b>{f.name}</b><span>trucks wait {f.avg_dwell_h} h on average; {f.detention_pct}% of visits run into detention charges</span></li>
          ))}
          <li><b>Book {Math.max(1, Math.round(s.avg_lead_days ?? 3))} days ahead</b><span>that is your usual lead time; more notice lets the brain put your load on a truck that is already nearby</span></li>
        </ul>
      </section>
    </>
  )
}

export default function Reports({ role, impact, onClose }) {
  const reports = usePoll(() => api.getReports(), 0)
  const learned = usePoll(() => api.getLearned(), 0)
  const [tab, setTab] = useState(role)
  const [carrier, setCarrier] = useState(null)
  const [shipper, setShipper] = useState(null)
  const rep = reports.data
  const lrn = learned.data

  const carrierIds = useMemo(() => (rep ? Object.keys(rep.carriers).sort((a, b) => rep.carriers[b].all.loads - rep.carriers[a].all.loads) : []), [rep])
  const shipperIds = useMemo(() => (rep ? Object.keys(rep.shippers).sort((a, b) => rep.shippers[b].all.loads - rep.shippers[a].all.loads) : []), [rep])
  const cid = carrier ?? carrierIds[0]
  const sid = shipper ?? shipperIds[0]

  return (
    <div className="rp-backdrop" onClick={onClose}>
      <article className="rp" onClick={(e) => e.stopPropagation()}>
        <header className="rp-head">
          <div>
            <span className="rp-kicker">Weekly report</span>
            <h2>{rep ? `Week of ${fmtDay(rep.week)} – ${fmtDay(rep.week_end)}` : 'Loading…'}</h2>
          </div>
          <div className="rp-tabs">
            {[['broker', 'Broker'], ['carrier', 'Carrier'], ['shipper', 'Manufacturer']].map(([k, label]) => (
              <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{label}</button>
            ))}
          </div>
          <div className="rp-actions">
            <button onClick={() => window.print()}>Save as PDF</button>
            <button className="x" onClick={onClose} aria-label="Close">✕</button>
          </div>
        </header>

        {tab !== 'broker' && rep && (
          <div className="rp-pick">
            {(tab === 'carrier' ? carrierIds : shipperIds).slice(0, 10).map((id) => (
              <button
                key={id}
                className={(tab === 'carrier' ? cid : sid) === id ? 'on' : ''}
                onClick={() => (tab === 'carrier' ? setCarrier(id) : setShipper(id))}
              >
                {(tab === 'carrier' ? rep.carriers[id] : rep.shippers[id]).name.replace(/ - .*/, '')}
              </button>
            ))}
          </div>
        )}

        <div className="rp-body">
          {!rep || !lrn ? (
            <div className="skeleton" style={{ height: 240 }} />
          ) : tab === 'broker' ? (
            <BrokerReport rep={rep} learned={lrn} impact={impact} />
          ) : tab === 'carrier' ? (
            <CarrierReport rep={rep} learned={lrn} id={cid} />
          ) : (
            <ShipperReport rep={rep} learned={lrn} id={sid} />
          )}
        </div>
        <footer className="rp-foot">Built from Meridian TMS records · updates every time a load closes</footer>
      </article>
    </div>
  )
}
