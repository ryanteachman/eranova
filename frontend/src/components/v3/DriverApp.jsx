import { useState } from 'react'
import './DriverApp.css'

// The driver's own app: today's load, the stops, one big next-step button.
// Status updates stay in local state; nothing writes to Meridian from here yet.

const EQ = { V: 'Dry van', R: 'Reefer', F: 'Flatbed', HS: 'Hotshot', SV: 'Sprinter' }
const STEPS = ['Dispatched', 'At pickup', 'Loaded', 'In transit', 'At delivery', 'Delivered']
const STATUS_STEP = {
  COVERED: 0,
  DISPATCHED: 0,
  AT_PICKUP: 1,
  PICKED_UP: 2,
  LOADED: 2,
  IN_TRANSIT: 3,
  AT_DELIVERY: 4,
  DELIVERED: 5,
}
// what the driver taps from each step, and where it takes them
const ACTIONS = {
  0: { label: "I'm at pickup", to: 1 },
  1: { label: 'Loaded, leaving', to: 3 },
  2: { label: 'Loaded, leaving', to: 3 },
  3: { label: 'Arrived at delivery', to: 4 },
  4: { label: 'Delivered · take POD photo', to: 5 },
}
const DELAY_REASONS = ['Traffic', 'Weather', 'Dock wait', 'Breakdown']
const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

const usd0 = (n) =>
  Number(n).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const num = (n) => Number(n).toLocaleString('en-US')

// window strings are facility-local wall clock ("2026-11-13T08:00:00"): read them as-is, no tz shift
function parseLocal(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(s || '')
  if (!m) return null
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]))
  return { dow: DOW[d.getUTCDay()], date: `${+m[2]}/${+m[3]}`, h: m[4] != null ? +m[4] : null, min: m[5] ?? '00', key: `${m[1]}${m[2]}${m[3]}` }
}
const hm = (p) => (p.h == null ? '' : `${p.h}:${p.min}`)
function fmtWindow(w) {
  if (!Array.isArray(w) || !w[0]) return null
  const a = parseLocal(w[0])
  const b = parseLocal(w[1])
  if (!a) return null
  if (!b) return `${a.dow} ${a.date} ${hm(a)}`
  if (a.key === b.key) return `${a.dow} ${a.date} · ${hm(a)}–${hm(b)}`
  return `${a.dow} ${hm(a)} – ${b.dow} ${hm(b)}`
}
// arrived / departed are real instants (UTC): show them in the stop's timezone
function fmtStamp(iso, tz) {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  const opts = { weekday: 'short', hour: 'numeric', minute: '2-digit' }
  try {
    return d.toLocaleString('en-US', tz ? { ...opts, timeZone: tz } : opts)
  } catch {
    return d.toLocaleString('en-US', opts)
  }
}
function fmtDay(s) {
  const p = parseLocal(s)
  return p ? `${p.dow} ${p.date}` : null
}
const cityOf = (x) => (typeof x === 'string' ? x : x?.city || '')

function apptLabel(a) {
  if (!a || a === 'NOT_REQUIRED') return { text: 'No appointment needed', kind: 'muted' }
  if (a === 'CONFIRMED') return { text: 'Appointment confirmed', kind: 'green' }
  if (a === 'PENDING' || a === 'REQUESTED') return { text: 'Appointment pending', kind: 'amber' }
  return { text: `Appointment ${String(a).toLowerCase().replace(/_/g, ' ')}`, kind: 'amber' }
}

function Frame({ children }) {
  return (
    <div className="da-phone">
      <div className="da-island" />
      <div className="da-screen">
        <div className="da-status">
          <span>9:41</span>
          <span className="da-sig">
            <i /><i /><i /><i />
            <b />
          </span>
        </div>
        {children}
      </div>
    </div>
  )
}

function Skeleton() {
  return (
    <Frame>
      <div className="da-scroll">
        <div className="da-head">
          <span className="da-sk" style={{ width: '45%', height: 22 }} />
          <span className="da-sk" style={{ width: '75%', height: 13, marginTop: 8 }} />
        </div>
        <div className="da-sk da-sk-card" style={{ height: 150 }} />
        <div className="da-sk da-sk-card" style={{ height: 56 }} />
        <div className="da-sk da-sk-card" style={{ height: 120 }} />
        <div className="da-sk da-sk-card" style={{ height: 120 }} />
      </div>
      <div className="da-bottom">
        <span className="da-sk da-sk-btn" />
      </div>
    </Frame>
  )
}

function Empty() {
  return (
    <Frame>
      <div className="da-empty">
        <span className="da-empty-ico">⌁</span>
        <b>No drivers yet</b>
        <span>When a carrier adds a driver to a load, their app shows up here.</span>
      </div>
    </Frame>
  )
}

function Progress({ step }) {
  return (
    <div className="da-card da-progress">
      <ol>
        {STEPS.map((s, i) => (
          <li key={s} className={i < step ? 'done' : i === step ? 'now' : ''}>
            <span className="da-pdot">{i < step ? '✓' : ''}</span>
            <span className="da-plabel">{s}</span>
          </li>
        ))}
      </ol>
      <div className="da-pbar">
        <span style={{ width: `${(step / (STEPS.length - 1)) * 100}%` }} />
      </div>
    </div>
  )
}

function Stop({ stop, arrived, departed, active }) {
  const isPick = stop.type === 'PICKUP'
  const appt = apptLabel(stop.appointment)
  const win = fmtWindow(stop.window)
  const arr = fmtStamp(arrived, stop.timezone)
  const dep = fmtStamp(departed, stop.timezone)
  const rules = (stop.rules || []).filter((r) => !/: none$/i.test(r))
  return (
    <div className={`da-card da-stop ${active ? 'active' : ''} ${departed ? 'past' : ''}`}>
      <div className="da-stop-top">
        <span className={`da-type ${isPick ? 'pick' : 'drop'}`}>{isPick ? 'Pickup' : 'Delivery'}</span>
        {win && <span className="da-win">{win}</span>}
      </div>
      <b className="da-fac">{stop.name}</b>
      <span className="da-addr">
        {[stop.address, [stop.city, stop.state].filter(Boolean).join(', ')].filter(Boolean).join(' · ')}
      </span>
      <span className={`da-appt ${appt.kind}`}>
        <i />
        {appt.text}
        {stop.confirmation && <em>#{stop.confirmation}</em>}
      </span>
      {rules.length > 0 && (
        <div className="da-chips">
          {rules.map((r) => (
            <span key={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</span>
          ))}
        </div>
      )}
      {stop.instructions && <p className="da-instr">{stop.instructions}</p>}
      {(arr || dep) && (
        <div className="da-times">
          {arr && (
            <span>
              Arrived <b>{arr}</b>
            </span>
          )}
          {dep && (
            <span>
              Departed <b>{dep}</b>
            </span>
          )}
        </div>
      )}
    </div>
  )
}

function NextLoads({ loads, destCity }) {
  return (
    <section className="da-section">
      <h4>Next up this week</h4>
      {loads && loads.length ? (
        <ul className="da-next">
          {loads.map((n, i) => {
            const o = cityOf(n.origin) || n.origin_city
            const d = cityOf(n.destination) || n.destination_city
            const day = fmtDay(n.pickup || n.pickup_date || n.window?.[0] || n.stops?.[0]?.window?.[0])
            return (
              <li key={n.shipment_id || i}>
                <div>
                  <b>
                    {o} → {d}
                  </b>
                  <span>
                    {[day && `Pickup ${day}`, n.miles != null && `${num(n.miles)} mi`].filter(Boolean).join(' · ')}
                  </span>
                </div>
                {n.pay != null && <em>{usd0(n.pay)}</em>}
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="da-muted-card">
          No next load yet. Dispatch is finding one near {destCity || 'your delivery'}.
        </p>
      )}
    </section>
  )
}

function DriverScreen({ driver, onToast }) {
  const load = driver.load
  const [step, setStep] = useState(() => (load ? STATUS_STEP[load.status] ?? 0 : 0))
  const [stamps, setStamps] = useState({}) // local arrived/departed per stop index
  const [delayOpen, setDelayOpen] = useState(false)
  const [reason, setReason] = useState(DELAY_REASONS[0])
  const [minutes, setMinutes] = useState('30')
  const [flash, setFlash] = useState(false)

  const first = (driver.name || '').split(' ')[0] || 'there'
  const eq = EQ[driver.equipment] ?? driver.equipment
  const stops = load?.stops || []
  const pickIdx = stops.findIndex((s) => s.type === 'PICKUP')
  const dropIdx = stops.map((s) => s.type).lastIndexOf('DELIVERY')
  const activeIdx = step <= 2 ? pickIdx : step <= 4 ? dropIdx : -1
  const action = ACTIONS[step]

  function advance() {
    if (!action) return
    const now = new Date().toISOString()
    setStamps((prev) => {
      const next = { ...prev }
      const put = (i, k) => {
        if (i < 0) return
        next[i] = { ...next[i], [k]: next[i]?.[k] || stops[i]?.[k] || now }
      }
      if (action.to === 1) put(pickIdx, 'arrived')
      if (action.to === 3) {
        put(pickIdx, 'arrived')
        put(pickIdx, 'departed')
      }
      if (action.to === 4) put(dropIdx, 'arrived')
      if (action.to === 5) {
        put(dropIdx, 'arrived')
        put(dropIdx, 'departed')
      }
      return next
    })
    setStep(action.to)
    setFlash(true)
    setTimeout(() => setFlash(false), 600)
    onToast?.(`Sent to dispatch: ${action.label}`, 'success')
  }

  function sendDelay() {
    setDelayOpen(false)
    onToast?.('Delay reported to dispatch', 'info')
  }

  return (
    <Frame>
      <div className="da-appbar">
        <span className="da-brand">
          <i />
          Return Trip · Driver
        </span>
      </div>

      <div className="da-scroll">
        <div className="da-head">
          <span className="da-hi">Hi {first}</span>
          <span className="da-kicker">
            {driver.carrier} · Truck {driver.truck}
            {eq ? ` · ${eq}` : ''}
          </span>
        </div>

        {!load ? (
          <p className="da-muted-card">No load assigned right now. Dispatch will send your next one here.</p>
        ) : (
          <>
            <div className="da-card da-today">
              <span className="da-label">Today</span>
              <span className="da-route">
                {load.origin?.city} <em>→</em> {load.destination?.city}
              </span>
              <span className="da-meta">
                Load {load.shipment_id}
                {load.pro ? ` · PRO ${load.pro}` : ''}
              </span>
              {load.commodity && <span className="da-commodity">{load.commodity}</span>}
              <div className="da-stats">
                {load.miles != null && (
                  <div>
                    <b>{num(load.miles)}</b>
                    <span>miles</span>
                  </div>
                )}
                {(load.pieces != null || load.weight_lb != null) && (
                  <div>
                    <b>{load.pieces != null ? num(load.pieces) : `${num(load.weight_lb)}`}</b>
                    <span>
                      {load.pieces != null ? 'pieces' : 'lb'}
                      {load.pieces != null && load.weight_lb != null ? ` · ${num(load.weight_lb)} lb` : ''}
                    </span>
                  </div>
                )}
                {load.pay != null && (
                  <div>
                    <b>{usd0(load.pay)}</b>
                    <span>your pay</span>
                  </div>
                )}
              </div>
              {load.special_instructions && <p className="da-note">{load.special_instructions}</p>}
            </div>

            <Progress step={step} />

            <section className="da-section">
              <h4>Stops</h4>
              <div className="da-stops">
                {stops.map((s, i) => (
                  <Stop
                    key={i}
                    stop={s}
                    active={i === activeIdx}
                    arrived={stamps[i]?.arrived || s.arrived}
                    departed={stamps[i]?.departed || s.departed}
                  />
                ))}
              </div>
            </section>

            <NextLoads loads={driver.next_loads} destCity={load.destination?.city} />
          </>
        )}
      </div>

      {load && (
        <div className="da-bottom">
          {delayOpen ? (
            <div className="da-delay">
              <div className="da-delay-row">
                <select value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Delay reason">
                  {DELAY_REASONS.map((r) => (
                    <option key={r}>{r}</option>
                  ))}
                </select>
                <label className="da-min">
                  <input
                    type="number"
                    min="5"
                    step="5"
                    value={minutes}
                    onChange={(e) => setMinutes(e.target.value)}
                    aria-label="Minutes late"
                  />
                  <span>min</span>
                </label>
              </div>
              <div className="da-delay-row">
                <button className="da-link" onClick={() => setDelayOpen(false)}>
                  Cancel
                </button>
                <button className="da-go small" onClick={sendDelay} disabled={!(Number(minutes) > 0)}>
                  Send to dispatch
                </button>
              </div>
            </div>
          ) : action ? (
            <>
              <button className={`da-go ${flash ? 'flash' : ''}`} onClick={advance} key={step}>
                {action.label}
              </button>
              <button className="da-link" onClick={() => setDelayOpen(true)}>
                Report a delay
              </button>
            </>
          ) : (
            <span className="da-done">✓ Delivered. POD sent to dispatch.</span>
          )}
          <span className="da-honest">Updates go to dispatch for approval before Meridian changes.</span>
        </div>
      )}
    </Frame>
  )
}

export default function DriverApp({ drivers, selectedId, onSelect, onToast }) {
  if (drivers == null) return <Skeleton />
  if (!drivers.length) return <Empty />
  const driver = drivers.find((d) => d.driver_id === selectedId) || drivers[0]
  // onSelect is owned by the parent's picker row; accepted here so the API stays symmetric
  void onSelect
  return <DriverScreen key={driver.driver_id} driver={driver} onToast={onToast} />
}
