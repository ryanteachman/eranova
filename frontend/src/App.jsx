import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './v3.css'
import { api, meridianLink } from './api.js'
import usePoll from './usePoll.js'
import Map3D from './components/v3/Map3D.jsx'
import { CardRow, FocusCard } from './components/v3/Cards.jsx'
import { Why } from './components/v2/TourDetail.jsx'
import { routeText } from './components/v2/TourList.jsx'
import ApprovalQueue from './components/ApprovalQueue.jsx'
import InboxPanel from './components/InboxPanel.jsx'
import AgentChat from './components/AgentChat.jsx'
import Toasts from './components/Toasts.jsx'
import Reports from './components/v3/Reports.jsx'
import InboxPage from './components/v3/InboxPage.jsx'
import DriverApp from './components/v3/DriverApp.jsx'
import ActivityPage from './components/v3/ActivityPage.jsx'

const ROLES = [
  { id: 'broker', label: 'Broker' },
  { id: 'carrier', label: 'Carrier' },
  { id: 'driver', label: 'Driver' },
  { id: 'shipper', label: 'Manufacturer' },
]
const EQ = { V: 'Dry van', R: 'Reefer', F: 'Flatbed', SV: 'Sprinter' }
const BROKER_VIEWS = [
  ['loops', 'Book now'],
  ['lanes', 'Find freight'],
  ['mine', 'My loops'],
]
const usd0 = (n) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const usd = (n) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
const day = (d) => new Date(`${d}T12:00:00`).toLocaleDateString('en-US', { weekday: 'short', month: 'numeric', day: 'numeric' })

// Each role becomes the same simple card: one title, one big number, one tag, one action.
function brokerItems(tours, scores = {}) {
  return tours.map((t) => ({
    id: t.tour_id,
    tourId: t.tour_id,
    kicker: `${t.carrier.name} · ${EQ[t.equipment] ?? t.equipment}`,
    title: t.name,
    big: `${t.totals.empty_miles_saved.toLocaleString()} mi`,
    bigNote: `fewer empty miles (≈ ${usd0(t.totals.cost_saved_usd)})`,
    tag: scores[t.carrier.vendor_id] ? `${t.totals.loaded_pct}% loaded · carrier ${scores[t.carrier.vendor_id].base_score}/100` : `${t.totals.loaded_pct}% loaded`,
    tone: t.status === 'booked' ? '' : 'amber',
    ...(scores[t.carrier.vendor_id] && {
      listTitle: `Carrier check · ${t.carrier.name} scores ${scores[t.carrier.vendor_id].base_score}/100`,
      list: scores[t.carrier.vendor_id].reasons.slice(0, 3).map((r, j) => ({ key: `${t.tour_id}-r${j}`, name: r, why: '' })),
    }),
    stats: [
      ['Truck loaded', `${t.totals.loaded_pct}% (was ${t.totals.one_by_one_loaded_pct}%)`],
      ['You collect · pay', `${usd0(t.totals.sell)} · ${usd0(t.totals.buy)}`],
      ['Your profit', usd0(t.totals.gp)],
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
    kicker: `${EQ[l.equipment] ?? l.equipment} trucks drive this route back empty`,
    title: `${l.origin.city} → ${l.destination.city}`,
    big: `${l.trucks_home_empty}`,
    bigNote: `empty trips since January · ${usd0(l.empty_cost_usd)} spent driving empty`,
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
    action: 'Find freight for this route',
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
    bigNote: 'offered for this truck this week',
    tag: `Home ${day(w.totals.home_by)}`,
    tone: w.status === 'accepted' ? '' : 'blue',
    listTitle: 'The week the broker offered',
    list: w.legs.map((l) => ({
      key: `${w.tour_id}-${l.seq}`,
      name: `${l.origin.city} → ${l.destination.city}`,
      why: l.kind === 'empty'
        ? `Empty · ${l.miles} mi`
        : `Pickup ${day(l.pickup)} · ${l.miles} mi · ${usd0(l.pay)}${l.status === 'needs_carrier' ? ' · new load' : ''}`,
    })),
    stats: [
      ['Truck loaded', `${w.totals.loaded_pct}%`],
      ['Per mile', `$${w.totals.per_mile}`],
      ['Idle days', `${w.totals.idle_days} (was ${w.standalone.idle_days})`],
    ],
    action: `Accept and send to ${w.carrier.driver.split(' ')[0]}`,
    done: w.status !== 'offered',
    doneLabel: w.status === 'accepted' ? `Accepted ✓ · on ${w.carrier.driver.split(' ')[0]}'s phone` : 'Counter sent',
    raw: w,
  }))
}

// Manufacturer: each plant is a supply hub; spokes go everywhere it ships (real Meridian loads).
const SPOKE_RGB = { delivered: [22, 163, 74], in_transit: [217, 119, 6], booked: [100, 116, 139], on_hold: [220, 38, 38], none_this_week: [203, 213, 225] }
const plantName = (h) => h.plant.replace(`${h.customer} - `, '').replace(/^.* - /, '')
function hubItems(hubs) {
  return hubs.map((h) => ({
    id: h.hub_id,
    tourId: h.hub_id,
    kicker: h.customer,
    title: plantName(h),
    big: `${h.week.loads}`,
    bigNote: `loads this week · ${h.spokes.length} ${h.spokes.length === 1 ? 'destination' : 'destinations'}`,
    tag: h.week.in_transit ? `${h.week.in_transit} on the road` : `${h.all.loads} loads since January`,
    tone: h.week.in_transit ? 'amber' : '',
    stats: [
      ['Delivered', `${h.week.delivered}`],
      ['On the road', `${h.week.in_transit}`],
      ['Booked, not picked up', `${h.week.booked}`],
      ['Spend this week', usd0(h.week.spend)],
    ],
    listTitle: 'Where this plant ships',
    list: h.spokes.slice(0, 4).map((sp) => ({
      name: sp.name,
      why: `${sp.loads_week} this week · ${sp.loads_all} since January${sp.on_time_pct != null ? ` · ${sp.on_time_pct}% on time` : ''}`,
    })),
    action: 'Live from Meridian',
    done: true,
    doneLabel: 'Live from Meridian',
    raw: h,
  }))
}
const hubAsTour = (h) => ({
  tour_id: h.hub_id, kind: 'hub', status: 'hub', equipment: '', name: plantName(h),
  legs: h.spokes.map((sp, i) => ({
    seq: i + 1, kind: 'existing', status: sp.status, origin: h.hub, destination: sp.destination,
    miles: sp.miles, path: sp.path, rgb: SPOKE_RGB[sp.status] ?? SPOKE_RGB.none_this_week,
  })),
})
// The carrier's week for a truck and the driver who drives it (same carrier + truck number in Meridian).
const weekDriverId = (w) => `${w.carrier.vendor_id}:${w.carrier.truck.replace(/^Truck /, '')}:${w.carrier.driver}`
const weekAsNextLoads = (w) => w.legs.filter((l) => l.kind !== 'empty').map((l) => ({
  shipment_id: `${w.tour_id}-${l.seq}`, origin: l.origin, destination: l.destination, pickup: l.pickup, miles: l.miles, pay: l.pay,
}))
const driverAsTour = (d) => ({
  tour_id: d.driver_id, kind: 'leg', status: 'driver', equipment: d.equipment, name: d.name,
  legs: [{ seq: 1, kind: 'existing', status: 'booked', origin: d.load.origin, destination: d.load.destination, miles: d.load.miles, path: d.load.path, rgb: [37, 65, 255] }],
})

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
  const [customerId, setCustomerId] = useState(null)
  const [driverId, setDriverId] = useState(null)
  const [activity, setActivity] = useState(null) // null | { focusPath }
  const [notices, setNotices] = useState([])
  const [view, setView] = useState('loops')
  const [targets, setTargets] = useState([])
  const [showReports, setShowReports] = useState(false)
  const [showInbox, setShowInbox] = useState(false)
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
  const hubs = usePoll(() => api.getHubs(), 0)
  const drivers = usePoll(() => api.getDrivers(), 0)
  const allActions = usePoll(() => api.getActions(), 3000)
  const prices = usePoll(() => api.getPriceSignals(), 0)
  const lanes = usePoll(() => api.getReturnLanes(), 0)
  const backtest = usePoll(() => api.getBacktest(), 0)
  const carrierCards = usePoll(() => api.getCarriers(), 0)

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
      const scores = Object.fromEntries((carrierCards.data?.items ?? []).map((c) => [c.vendor_id, c]))
      return brokerItems(tours.data.items.filter((t) => (view === 'mine' ? t.status === 'booked' : t.status !== 'booked')), scores)
    }
    if (role === 'carrier') return weeks.data ? carrierItems(weeks.data.items.filter((w) => w.carrier.vendor_id === carrierId)) : null
    if (role === 'driver') return null
    if (!hubs.data) return null
    const cid = customerId ?? hubs.data.items[0]?.customer_id
    return hubItems(hubs.data.items.filter((h) => h.customer_id === cid))
  }, [role, view, targets, carrierId, customerId, tours.data, weeks.data, hubs.data, lanes.data, carrierCards.data])

  const pickKey = role === 'broker' ? `broker-${view}` : role
  const selected = items?.find((it) => it.id === picked[pickKey]) ?? items?.[0] ?? null
  const [ranks, setRanks] = useState({}) // tour_id -> Ryan's ranking for the loop's new load
  const newLeg = role === 'broker' && view !== 'lanes' ? selected?.raw?.legs?.find((l) => l.status === 'needs_carrier' && l.shipment_id) : null
  useEffect(() => {
    if (!newLeg || ranks[selected.id]) return
    const id = selected.id
    api.rankCarriers({ shipment_id: newLeg.shipment_id }).then((r) => setRanks((x) => ({ ...x, [id]: r }))).catch(() => {})
  }, [newLeg?.shipment_id]) // eslint-disable-line react-hooks/exhaustive-deps
  const rank = selected && ranks[selected.id]
  const rankText = (() => {
    if (!rank || !newLeg) return null
    const mine = selected.raw.carrier.vendor_id
    const pos = rank.eligible.findIndex((c) => c.vendor_id === mine)
    const top = rank.eligible[0]
    const lane = `${newLeg.origin.city} → ${newLeg.destination.city}`
    if (pos === 0) return `Best-ranked carrier for the new ${lane} load out of ${rank.eligible.length + rank.excluded.length} checked.`
    if (pos > 0) return `Ranked #${pos + 1} for the new ${lane} load. Top pick is ${top.legal_name} (${top.score}), but ${selected.raw.carrier.name} already has a truck there from the load before it.`
    return `Not in the top ${rank.eligible.length} for the new ${lane} load. Top pick is ${top.legal_name} (${top.score}).`
  })()
  const focus = selected ? { ...selected, link: links[selected.id], explain: selected.explain ?? rankText } : null

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
        announce(action)
        setLinks((l) => ({ ...l, [selected.id]: meridianLink(action.result) }))
      } else if (role === 'carrier') {
        await api.respondWeek(selected.raw.tour_id, 'accept')
        toast(`Week accepted. It's on ${selected.raw.carrier.driver}'s phone now, home ${day(selected.raw.totals.home_by)}.`, 'success')
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

  const hubCustomers = useMemo(() => {
    const m = new Map()
    ;(hubs.data?.items ?? []).forEach((h) => {
      const c = m.get(h.customer_id) ?? { id: h.customer_id, name: h.customer, plants: 0, loads: 0 }
      c.plants += 1
      c.loads += h.week.loads
      m.set(h.customer_id, c)
    })
    return [...m.values()].sort((a, b) => b.loads - a.loads)
  }, [hubs.data])
  const activeCustomer = customerId ?? hubCustomers[0]?.id
  const driverList = drivers.data?.items ?? []
  const baseDriver = driverList.find((d) => d.driver_id === driverId) ?? driverList[0] ?? null
  // once dispatch accepts a week for this truck, its loads show up on the driver's phone
  const acceptedWeek = baseDriver && allWeeks.find((w) => w.status === 'accepted' && weekDriverId(w) === baseDriver.driver_id)
  const driver = baseDriver && acceptedWeek ? { ...baseDriver, next_loads: weekAsNextLoads(acceptedWeek) } : baseDriver

  // Every approval pops a notice. If it wrote to Meridian (a quote), the notice links to it.
  const seenWrites = useRef(null)
  const announce = useCallback((a) => {
    if (!a || a.status !== 'done') return
    if (seenWrites.current?.has(a.action_id)) return
    seenWrites.current?.add(a.action_id)
    const r = a.result || {}
    const wrote = Boolean(r.quote_id || r.meridian_url)
    const path = r.meridian_url ? new URL(r.meridian_url, 'http://x').pathname : r.quote_id ? `/quotes/${r.quote_id}` : null
    const id = a.action_id
    setNotices((n) => [...n, {
      id,
      head: wrote ? 'Meridian updated' : 'Approved',
      title: r.quote_id ? `Quote ${r.quote_id} created` : r.summary || a.title,
      amount: r.sell_total,
      path: wrote ? path : null,
    }])
    setTimeout(() => setNotices((n) => n.filter((x) => x.id !== id)), 9000)
  }, [])
  useEffect(() => {
    if (!allActions.data) return
    const writes = allActions.data.items.filter((a) => a.status === 'done')
    if (seenWrites.current === null) {
      seenWrites.current = new Set(writes.map((a) => a.action_id)) // don't announce what happened before the page opened
      return
    }
    writes.forEach(announce) // catches approvals made anywhere else (another tab, a teammate)
  }, [allActions.data, announce])

  const sub = {
    broker: {
      loops: <><b>{readyTours.length} {readyTours.length === 1 ? 'loop' : 'loops'}</b> ready to book · <b>{waiting.toLocaleString()} empty miles</b> to save</>,
      lanes: bt ? <><b>{bt.return_lanes.lanes} routes</b> where your trucks come back empty · <b>{bt.return_lanes.share_of_empty}%</b> of all empty miles</> : null,
      mine: <><b>{bookedTours.length}</b> {bookedTours.length === 1 ? 'loop' : 'loops'} booked</>,
    }[view],
    carrier: <>Dispatch: accept a full week for each truck · it goes straight to the driver's phone</>,
    driver: <>The driver's app: today's load, every stop, one button for the next step</>,
    shipper: <>Each plant is a supply hub · lines show where its goods ship this week</>,
  }[role]

  return (
    <div className="v3">
      <div className="v3-map">
        <Map3D
          tours={
            role === 'shipper' ? (hubs.data?.items ?? []).filter((h) => h.customer_id === activeCustomer).map(hubAsTour)
              : role === 'driver' ? (driver ? [driverAsTour(driver)] : [])
              : role === 'broker' && view === 'lanes' ? (lanes.data?.items ?? []).map(laneAsTour)
              : allTours.filter((t) => role !== 'broker' || (view === 'mine' ? t.status === 'booked' : true))
          }
          focusTourId={role === 'driver' ? driver?.driver_id ?? null : focusOpen || role === 'carrier' ? selected?.tourId ?? null : null}
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
      {role === 'shipper' && (
        <div className="v3-filters">
          {hubCustomers.map((c) => (
            <button key={c.id} className={`glass ${activeCustomer === c.id ? 'on' : ''}`} onClick={() => { setCustomerId(c.id); setFocusOpen(true) }}>
              {c.name.replace(' - ', ' · ')} <em>{c.plants} {c.plants === 1 ? 'plant' : 'plants'}</em>
            </button>
          ))}
        </div>
      )}
      {role === 'driver' && (
        <div className="v3-filters">
          {[...driverList.slice(0, 12), ...(driver && !driverList.slice(0, 12).some((d) => d.driver_id === driver.driver_id) ? [driver] : [])].map((d) => (
            <button key={d.driver_id} className={`glass ${driver?.driver_id === d.driver_id ? 'on' : ''}`} onClick={() => setDriverId(d.driver_id)}>
              {d.name} <em>Truck {d.truck}</em>
            </button>
          ))}
        </div>
      )}
      <div className="v3-sub glass">{sub}</div>
      </div>

      <div className="v3-more">
        <button className="glass" onClick={() => setShowReports(true)}>Reports</button>
        <button className="glass" onClick={() => setActivity({})}>Activity</button>
        <button className="glass meridian" onClick={() => setActivity({ meridian: true })}>View Meridian ↗</button>
        <button className="glass" onClick={() => { setDrawer(null); setShowInbox(true) }}>Inbox</button>
        {[
          ['approvals', 'Approvals'],
          ['agent', 'Ask agent'],
        ].map(([id, label]) => (
          <button key={id} className={`glass ${drawer === id ? 'on' : ''}`} onClick={() => setDrawer(drawer === id ? null : id)}>
            {label}
            {id === 'approvals' && pendingCount > 0 && <span className="n" />}
          </button>
        ))}
      </div>

      {role === 'driver' && !drawer && (
        <div className="v3-phone">
          <DriverApp
            key={driver?.driver_id}
            drivers={drivers.data ? driverList.map((d) => (d.driver_id === driver?.driver_id ? driver : d)) : null}
            selectedId={driver?.driver_id}
            onSelect={setDriverId}
            onToast={toast}
          />
        </div>
      )}

      {role !== 'driver' && focusOpen && !drawer && (
        <FocusCard
          item={focus}
          busy={busy}
          onAction={act}
          onClose={() => setFocusOpen(false)}
          onWhy={
            role === 'broker' && view !== 'lanes' ? () => setDrawer('why')
              : role === 'carrier' && selected?.raw.status === 'accepted' ? () => { setDriverId(weekDriverId(selected.raw)); setRole('driver') }
              : null
          }
          whyLabel={role === 'carrier' ? `See ${selected?.raw.carrier.driver.split(' ')[0]}'s phone →` : undefined}
        />
      )}

      {drawer && (
        <aside className="v3-drawer">
          <header>
            <b>{{ approvals: 'Approvals', inbox: 'Inbox', agent: 'Ask the agent', why: 'Why this loop' }[drawer]}</b>
            <button className="x" onClick={() => setDrawer(null)} aria-label="Close">✕</button>
          </header>
          <div className={`body ${drawer === 'agent' ? 'flush' : ''}`}>
            {drawer === 'approvals' && <ApprovalQueue pending={pending} onApproved={(a) => { announce(a); tours.refresh() }} onToast={toast} />}
            {drawer === 'inbox' && <InboxPanel onToast={toast} onActionsCreated={() => pending.refresh()} />}
            {drawer === 'agent' && <AgentChat onError={(m) => toast(m, 'error')} />}
            {drawer === 'why' && selected?.raw?.decisions && <Why tour={selected.raw} priceLanes={priceLanes} />}
          </div>
        </aside>
      )}

      {role === 'shipper' && (
        <div className="v3-legend glass">
          <span><i style={{ background: '#16a34a' }} />Delivered</span>
          <span><i style={{ background: '#d97706' }} />On the road</span>
          <span><i style={{ background: '#64748b' }} />Booked</span>
          <span><i style={{ background: '#cbd5e1' }} />No load this week</span>
        </div>
      )}
      {role === 'broker' && (
        <div className="v3-legend glass">
          <span><i style={{ background: '#16a34a' }} />Booked</span>
          <span><i style={{ background: '#d97706' }} />Ready to book</span>
          <span><i style={{ background: '#2541ff' }} />Needs freight</span>
          <span><i className="dash" />Empty drive</span>
          {focusOpen ? (
            <button onClick={() => setFocusOpen(false)}>See all loops</button>
          ) : null}
        </div>
      )}

      {items && items.length === 0 && role === 'broker' && (
        <div className="v3-cards"><div className="v3-card glass" style={{ cursor: 'default' }}>
          <span className="kicker">{view === 'mine' ? 'Nothing booked yet' : 'All caught up'}</span>
          <span className="title">{view === 'mine' ? 'Book a loop and it shows up here with its money and savings.' : 'Every loop the brain found is booked. Check Find freight for the next ones.'}</span>
        </div></div>
      )}
      <CardRow items={items} selectedId={focusOpen ? selected?.id : null} onSelect={select} />
      {showInbox && (
        <InboxPage
          onToast={toast}
          onApproved={announce}
          onActionsChanged={() => {
            pending.refresh()
            tours.refresh()
          }}
          onClose={() => setShowInbox(false)}
        />
      )}
      {showReports && (
        <Reports
          role={role}
          impact={{ loops: bookedTours.length, miles: money.miles, saved: money.saved, margin: money.in - money.out }}
          onClose={() => setShowReports(false)}
        />
      )}
      {activity && (
        <ActivityPage
          focusPath={activity.focusPath}
          startOnMeridian={!!activity.meridian}
          onClose={() => setActivity(null)}
        />
      )}

      {/* a pop-up every time an approved action changes Meridian */}
      <div className="m-notices">
        {notices.map((n) => (
          <div key={n.id} className="m-notice">
            <span className="m-dot" />
            <div>
              <b>{n.head}</b>
              <span>{n.title}{n.amount != null ? ` · ${usd(n.amount)}` : ''}</span>
            </div>
            {n.path && <button onClick={() => { setActivity({ focusPath: n.path, meridian: true }); setNotices((x) => x.filter((y) => y.id !== n.id)) }}>View in Meridian</button>}
          </div>
        ))}
      </div>
      <Toasts items={toasts} />
    </div>
  )
}
