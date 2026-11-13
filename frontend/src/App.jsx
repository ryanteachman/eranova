import { useCallback, useMemo, useState } from 'react'
import './v3.css'
import { api, meridianLink } from './api.js'
import usePoll from './usePoll.js'
import Map3D from './components/v3/Map3D.jsx'
import { CardRow, FocusCard } from './components/v3/Cards.jsx'
import { Why } from './components/v2/TourDetail.jsx'
import { routeText } from './components/v2/TourList.jsx'
import PhoneWeek from './components/v3/PhoneWeek.jsx'
import ApprovalQueue from './components/ApprovalQueue.jsx'
import InboxPanel from './components/InboxPanel.jsx'
import AgentChat from './components/AgentChat.jsx'
import Toasts from './components/Toasts.jsx'
import Reports from './components/v3/Reports.jsx'

const ROLES = [
  { id: 'broker', label: 'Broker' },
  { id: 'carrier', label: 'Carrier' },
  { id: 'shipper', label: 'Manufacturer' },
]
const EQ = { V: 'Dry van', R: 'Reefer', F: 'Flatbed', SV: 'Sprinter' }
const BROKER_VIEWS = [
  ['loops', 'Ready to book'],
  ['lanes', 'Empty trips to fill'],
  ['mine', 'My loops'],
]
const usd0 = (n) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const usd = (n) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
const day = (d) => new Date(`${d}T12:00:00`).toLocaleDateString('en-US', { weekday: 'short', month: 'numeric', day: 'numeric' })

// Each role becomes the same simple card: one title, one big number, one tag, one action.
function brokerItems(tours) {
  return tours.map((t) => ({
    id: t.tour_id,
    tourId: t.tour_id,
    kicker: `${t.carrier.name} · ${EQ[t.equipment] ?? t.equipment}`,
    title: t.name,
    big: `${t.totals.empty_miles_saved.toLocaleString()} mi`,
    bigNote: `fewer empty miles (≈ ${usd0(t.totals.cost_saved_usd)})`,
    tag: `${t.totals.loaded_pct}% loaded`,
    tone: t.status === 'booked' ? '' : 'amber',
    stats: [
      ['Truck loaded', `${t.totals.loaded_pct}% (was ${t.totals.one_by_one_loaded_pct}%)`],
      ['You collect · pay', `${usd0(t.totals.sell)} · ${usd0(t.totals.buy)}`],
      ['Home', day(t.window.home_by)],
    ],
    action: 'Book this loop',
    done: t.status === 'booked',
    doneLabel: 'Booked ✓',
    raw: t,
  }))
}

// A return lane: trucks that drive this route home empty today (real Meridian history).
function laneItems(lanes, targets) {
  return lanes.map((l) => ({
    id: l.lane_id,
    tourId: l.lane_id,
    kicker: `${EQ[l.equipment] ?? l.equipment} trucks drive this home empty`,
    title: `${l.origin.city} → ${l.destination.city}`,
    big: `${l.trucks_home_empty} trips`,
    bigNote: `home empty since January · ${usd0(l.empty_cost_usd)} wasted`,
    tag: `about ${Math.max(1, Math.round(l.per_month))} a month`,
    tone: targets.includes(l.lane_id) ? '' : 'blue',
    explain: `Your trucks deliver into ${l.origin.city}, then drive back to ${l.destination.city} with nothing in the trailer. Find a shipper with freight going ${l.origin.city} → ${l.destination.city} and each of these trips earns money instead of costing it.`,
    stats: [
      ['Wasted driving empty', usd0(l.empty_cost_usd)],
      ['One load on this trip pays', usd0(l.market_rate)],
      ['If you fill them all', usd0(l.freight_value_usd)],
    ],
    listTitle: 'Who could ship it',
    list: l.leads.slice(0, 3),
    action: 'Find freight for this trip',
    done: targets.includes(l.lane_id),
    doneLabel: 'The agent is looking ✓',
    raw: l,
  }))
}

// Return lanes drawn like loops so the map can show them (blue = freight to find).
const laneAsTour = (l) => ({
  tour_id: l.lane_id, status: 'lane', equipment: l.equipment, name: `${l.origin.city} → ${l.destination.city}`,
  legs: [{ seq: 1, kind: 'existing', status: 'missing', origin: l.origin, destination: l.destination, miles: l.road_miles, path: l.path }],
})

function carrierItems(weeks) {
  return weeks.map((w) => ({
    id: w.tour_id,
    tourId: w.tour_id,
    kicker: `${w.carrier.truck} · ${w.carrier.driver} · ${EQ[w.carrier.equipment] ?? w.carrier.equipment}`,
    title: routeText(w),
    big: usd0(w.totals.pay),
    bigNote: 'this week',
    tag: `Home ${day(w.totals.home_by)}`,
    tone: w.status === 'accepted' ? '' : 'blue',
    stats: [
      ['Truck loaded', `${w.totals.loaded_pct}%`],
      ['Per mile', `$${w.totals.per_mile}`],
      ['Idle days', `${w.totals.idle_days} (was ${w.standalone.idle_days})`],
    ],
    action: 'Accept the week',
    done: w.status !== 'offered',
    doneLabel: w.status === 'accepted' ? 'Accepted ✓' : 'Counter sent',
    raw: w,
  }))
}

function shipperItems(offers) {
  return offers.map((o) => ({
    id: o.offer_id,
    tourId: o.tour_id,
    kicker: o.shipper.name,
    title: o.title,
    big: usd0(o.savings),
    bigNote: 'you save',
    tag: day(o.date),
    tone: o.status === 'accepted' ? '' : 'blue',
    stats: [
      ['Price', usd(o.price)],
      ['Market', usd(o.market_price)],
      ['Route', `${o.lane.origin.city} → ${o.lane.destination.city}`],
    ],
    action: 'Accept offer',
    done: o.status !== 'open',
    doneLabel: o.status === 'accepted' ? 'Accepted ✓' : 'Declined',
    raw: o,
  }))
}

export default function App() {
  const [role, setRole] = useState('broker')
  const [picked, setPicked] = useState({ broker: 'T-101', carrier: 'T-101', shipper: 'O-301' })
    const [carrierId, setCarrierId] = useState('SUNRIDGE')
  const [view, setView] = useState('loops')
  const [targets, setTargets] = useState([])
  const [showReports, setShowReports] = useState(false)
  const [focusOpen, setFocusOpen] = useState(true)
  const [drawer, setDrawer] = useState(null)
  const [busy, setBusy] = useState(false)
  const [links, setLinks] = useState({})
  const [toasts, setToasts] = useState([])

  const network = usePoll(() => api.getNetwork(), 0)
  const pending = usePoll(() => api.getActions('pending'), 3000)
  const tours = usePoll(() => api.getTours(), 4000)
  const weeks = usePoll(() => api.getCarrierWeeks(), 4000)
  const offers = usePoll(() => api.getOffers(), 4000)
  const prices = usePoll(() => api.getPriceSignals(), 0)
  const lanes = usePoll(() => api.getReturnLanes(), 0)
  const backtest = usePoll(() => api.getBacktest(), 0)

  const toast = useCallback((text, kind = 'info') => {
    const id = Math.random()
    setToasts((t) => [...t, { id, text, kind }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000)
  }, [])

  const allTours = tours.data?.items ?? []
  const allWeeks = weeks.data?.items ?? []
  const carriers = useMemo(() => {
    const m = new Map()
    allWeeks.forEach((w) => m.set(w.carrier.vendor_id, { id: w.carrier.vendor_id, name: w.carrier.name, trucks: (m.get(w.carrier.vendor_id)?.trucks ?? 0) + 1 }))
    return [...m.values()].sort((a, b) => b.trucks - a.trucks)
  }, [weeks.data]) // eslint-disable-line react-hooks/exhaustive-deps

  const items = useMemo(() => {
    if (role === 'broker') {
      if (view === 'lanes') return lanes.data ? laneItems(lanes.data.items, targets) : null
      if (!tours.data) return null
      return brokerItems(tours.data.items.filter((t) => (view === 'mine' ? t.status === 'booked' : t.status !== 'booked')))
    }
    if (role === 'carrier') return weeks.data ? carrierItems(weeks.data.items.filter((w) => w.carrier.vendor_id === carrierId)) : null
    return offers.data ? shipperItems(offers.data.items) : null
  }, [role, view, targets, carrierId, tours.data, weeks.data, offers.data, lanes.data])

  const pickKey = role === 'broker' ? `broker-${view}` : role
  const selected = items?.find((it) => it.id === picked[pickKey]) ?? items?.[0] ?? null
  const focus = selected ? { ...selected, link: links[selected.id] } : null

  const priceLanes = useMemo(() => {
    if (!prices.data) return []
    const byId = Object.fromEntries(prices.data.signals.map((s) => [s.id, s]))
    return prices.data.lanes.map((l) => ({ ...l, quotes: l.signals.map((id) => byId[id]).filter(Boolean) }))
  }, [prices.data])

  const readyTours = (tours.data?.items ?? []).filter((t) => t.status !== 'booked')
  const waiting = readyTours.reduce((s, t) => s + t.totals.empty_miles_saved, 0)
  const pendingCount = pending.data?.items?.length ?? 0

  function select(id) {
    setPicked((p) => ({ ...p, [pickKey]: id }))
    setFocusOpen(true)
    setDrawer(null)
  }

  async function act() {
    if (!selected) return
    setBusy(true)
    try {
      if (role === 'broker' && view === 'lanes') {
        setTargets((t) => [...t, selected.id])
        toast(`The agent is now watching email and calls for freight going ${selected.title}.`, 'success')
      } else if (role === 'broker') {
        const action = await api.approve(selected.raw.action_id)
        setLinks((l) => ({ ...l, [selected.id]: meridianLink(action.result) }))
        toast(action.result?.summary ?? 'Loop booked', 'success')
      } else if (role === 'carrier') {
        await api.respondWeek(selected.raw.tour_id, 'accept')
        toast(`Week accepted. ${selected.raw.carrier.name} is home ${day(selected.raw.totals.home_by)}.`, 'success')
      } else {
        await api.respondOffer(selected.raw.offer_id, 'accept')
        toast(`${selected.raw.shipper.name} accepted. The loop closes.`, 'success')
      }
      pending.refresh()
      tours.refresh()
      weeks.refresh()
      offers.refresh()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const bookedTours = allTours.filter((t) => t.status === 'booked')
  const counts = { loops: readyTours.length, lanes: lanes.data?.items.length ?? 0, mine: bookedTours.length }
  const money = bookedTours.reduce(
    (m, t) => ({ in: m.in + t.totals.sell, out: m.out + t.totals.buy, miles: m.miles + t.totals.empty_miles_saved, saved: m.saved + t.totals.cost_saved_usd }),
    { in: 0, out: 0, miles: 0, saved: 0 },
  )
  const bt = backtest.data

  const sub = {
    broker: {
      loops: <><b>{readyTours.length} {readyTours.length === 1 ? 'loop' : 'loops'}</b> ready to book · <b>{waiting.toLocaleString()} empty miles</b> to save</>,
      lanes: bt ? <>Your trucks drove <b>{bt.one_by_one.empty_miles.toLocaleString()} miles empty</b> this year. <b>{bt.return_lanes.share_of_empty}%</b> of it is these {bt.return_lanes.lanes} trips home.</> : null,
      mine: <><b>{bookedTours.length}</b> {bookedTours.length === 1 ? 'loop' : 'loops'} booked</>,
    }[view],
    carrier: <>Each truck gets a full week that ends at home</>,
    shipper: <>Trucks already coming your way</>,
  }[role]

  return (
    <div className="v3">
      <div className="v3-map">
        <Map3D
          tours={role === 'broker' && view === 'lanes' ? (lanes.data?.items ?? []).map(laneAsTour) : allTours.filter((t) => role !== 'broker' || (view === 'mine' ? t.status === 'booked' : true))}
          focusTourId={focusOpen || role === 'carrier' ? selected?.tourId ?? null : null}
          onSelectTour={(id) => {
            if (role === 'broker') select(id)
          }}
          pad={{ top: 170, right: 400, bottom: 250, left: 40 }}
        />
      </div>

      <nav className="v3-nav glass" aria-label="View as">
        {ROLES.map((r) => (
          <button key={r.id} className={role === r.id ? 'on' : ''} onClick={() => { setRole(r.id); setDrawer(null); setFocusOpen(true) }}>
            {r.label}
          </button>
        ))}
      </nav>
      <div className="v3-under">
      {role === 'broker' && (
        <div className="v3-filters">
          {BROKER_VIEWS.map(([id, label]) => (
            <button key={id} className={`glass ${view === id ? 'on' : ''}`} onClick={() => { setView(id); setFocusOpen(true); setDrawer(null) }}>
              {label} <em>{counts[id]}</em>
            </button>
          ))}
        </div>
      )}
      {role === 'broker' && view === 'mine' && (
        <div className="v3-money">
          <div className="glass in"><small>Coming in (customers)</small><b>{usd0(money.in)}</b></div>
          <div className="glass out"><small>Going out (carriers)</small><b>{usd0(money.out)}</b></div>
          <div className="glass margin"><small>Your margin</small><b>{usd0(money.in - money.out)}</b></div>
          <div className="glass saved"><small>Empty miles saved</small><b>{money.miles.toLocaleString()} mi</b></div>
        </div>
      )}
      {role === 'carrier' && (
        <div className="v3-filters">
          {carriers.map((c) => (
            <button key={c.id} className={`glass ${carrierId === c.id ? 'on' : ''}`} onClick={() => setCarrierId(c.id)}>
              {c.name} <em>{c.trucks} {c.trucks === 1 ? 'truck' : 'trucks'}</em>
            </button>
          ))}
        </div>
      )}
      <div className="v3-sub glass">{sub}</div>
      </div>

      <div className="v3-more">
        <button className="glass" onClick={() => setShowReports(true)}>Reports</button>
        {[
          ['approvals', 'Approvals'],
          ['inbox', 'Inbox'],
          ['agent', 'Ask agent'],
        ].map(([id, label]) => (
          <button key={id} className={`glass ${drawer === id ? 'on' : ''}`} onClick={() => setDrawer(drawer === id ? null : id)}>
            {label}
            {id === 'approvals' && pendingCount > 0 && <span className="n" />}
          </button>
        ))}
      </div>

      {role === 'carrier' && !drawer && selected && (
        <div className="v3-phone">
          <PhoneWeek
            key={selected.raw.tour_id}
            week={selected.raw}
            onResponded={() => {
              weeks.refresh()
              tours.refresh()
            }}
            onToast={toast}
          />
        </div>
      )}

      {role !== 'carrier' && focusOpen && !drawer && (
        <FocusCard
          item={focus}
          busy={busy}
          onAction={act}
          onClose={() => setFocusOpen(false)}
          onWhy={role === 'broker' && view !== 'lanes' ? () => setDrawer('why') : null}
        />
      )}

      {drawer && (
        <aside className="v3-drawer">
          <header>
            <b>{{ approvals: 'Approvals', inbox: 'Inbox', agent: 'Ask the agent', why: 'Why this loop' }[drawer]}</b>
            <button className="x" onClick={() => setDrawer(null)} aria-label="Close">✕</button>
          </header>
          <div className={`body ${drawer === 'agent' ? 'flush' : ''}`}>
            {drawer === 'approvals' && <ApprovalQueue pending={pending} onApproved={() => tours.refresh()} onToast={toast} />}
            {drawer === 'inbox' && <InboxPanel onToast={toast} onActionsCreated={() => pending.refresh()} />}
            {drawer === 'agent' && <AgentChat onError={(m) => toast(m, 'error')} />}
            {drawer === 'why' && selected?.raw?.decisions && <Why tour={selected.raw} priceLanes={priceLanes} />}
          </div>
        </aside>
      )}

      {role !== 'carrier' && (
        <div className="v3-legend glass">
          <span><i style={{ background: '#16a34a' }} />Booked</span>
          <span><i style={{ background: '#d97706' }} />Ready to book</span>
          <span><i style={{ background: '#2541ff' }} />Found by the brain</span>
          {focusOpen ? (
            <button onClick={() => setFocusOpen(false)}>See all loops</button>
          ) : null}
        </div>
      )}

      {items && items.length === 0 && role === 'broker' && (
        <div className="v3-cards"><div className="v3-card glass" style={{ cursor: 'default' }}>
          <span className="kicker">{view === 'mine' ? 'Nothing booked yet' : 'All caught up'}</span>
          <span className="title">{view === 'mine' ? 'Book a loop and it shows up here with its money and savings.' : 'Every loop the brain found is booked. Check the return lanes to win.'}</span>
        </div></div>
      )}
      <CardRow items={items} selectedId={focusOpen ? selected?.id : null} onSelect={select} />
      {showReports && (
        <Reports
          role={role}
          impact={{ loops: bookedTours.length, miles: money.miles, saved: money.saved, margin: money.in - money.out }}
          onClose={() => setShowReports(false)}
        />
      )}
      <Toasts items={toasts} />
    </div>
  )
}
