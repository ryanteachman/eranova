import { useCallback, useMemo, useState } from 'react'
import './v2.css'
import { api, MERIDIAN_WEB_URL, USE_MOCK } from '../api.js'
import usePoll from '../usePoll.js'
import NetworkMap from '../components/NetworkMap.jsx'
import TourList from '../components/v2/TourList.jsx'
import TourDetail from '../components/v2/TourDetail.jsx'
import CarrierWeek from '../components/CarrierWeek.jsx'
import ShipperOffers from '../components/ShipperOffers.jsx'
import ApprovalQueue from '../components/ApprovalQueue.jsx'
import InboxPanel from '../components/InboxPanel.jsx'
import AgentChat from '../components/AgentChat.jsx'
import PriceSignals from '../components/PriceSignals.jsx'
import CityPanel from '../components/CityPanel.jsx'
import Toasts from '../components/Toasts.jsx'

const ROLES = [
  { id: 'broker', label: 'Broker' },
  { id: 'carrier', label: 'Carrier' },
  { id: 'shipper', label: 'Manufacturer' },
]
const DRAWERS = { approvals: 'Approvals', inbox: 'Inbox', agent: 'Ask the agent', prices: 'Prices from calls and emails', city: 'City' }
const usd0 = (n) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

// Map padding so routes are never hidden under the floating panels.
const PAD = {
  broker: { paddingTopLeft: [420, 90], paddingBottomRight: [40, 360] },
  carrier: { paddingTopLeft: [420, 90], paddingBottomRight: [470, 40] },
  shipper: { paddingTopLeft: [500, 90], paddingBottomRight: [40, 40] },
}

export default function App() {
  const [role, setRole] = useState('broker')
  const [drawer, setDrawer] = useState(null)
  const [tourId, setTourId] = useState('T-101')
  const [carrierTourId, setCarrierTourId] = useState('T-101')
  const [shipperId, setShipperId] = useState(null)
  const [focusOffer, setFocusOffer] = useState(null)
  const [city, setCity] = useState(null)
  const [toasts, setToasts] = useState([])

  const network = usePoll(() => api.getNetwork(), 0)
  const pending = usePoll(() => api.getActions('pending'), 3000)
  const tours = usePoll(() => api.getTours(), 4000)
  const weeks = usePoll(() => api.getCarrierWeeks(), 4000)
  const offers = usePoll(() => api.getOffers(), 4000)
  const prices = usePoll(() => api.getPriceSignals(), 0)

  const toast = useCallback((text, kind = 'info') => {
    const id = Math.random()
    setToasts((t) => [...t, { id, text, kind }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500)
  }, [])

  const tourList = tours.data?.items ?? null
  const tour = tourList?.find((t) => t.tour_id === tourId)
  const pendingIds = (pending.data?.items ?? []).map((a) => a.action_id)
  const totals = network.data?.totals

  const money = useMemo(() => {
    const list = tourList ?? []
    const unlocked = list.filter((t) => t.status === 'booked').reduce((s, t) => s + t.totals.profit_unlocked, 0)
    const all = list.reduce((s, t) => s + t.totals.profit_unlocked, 0)
    const loaded = list.length ? Math.round(list.reduce((s, t) => s + t.totals.loaded_pct, 0) / list.length) : 0
    return { unlocked, waiting: all - unlocked, loaded }
  }, [tourList])

  // Price lanes with their quotes attached, for the "Why this loop" evidence.
  const priceLanes = useMemo(() => {
    if (!prices.data) return []
    const byId = Object.fromEntries(prices.data.signals.map((s) => [s.id, s]))
    return prices.data.lanes.map((l) => ({ ...l, quotes: l.signals.map((id) => byId[id]).filter(Boolean) }))
  }, [prices.data])

  function refreshAll() {
    pending.refresh()
    tours.refresh()
    weeks.refresh()
  }

  function pickRole(r) {
    setRole(r)
    setDrawer(null)
  }

  // What the map shows depends on who is looking.
  const focusTourId = role === 'broker' ? tourId : role === 'carrier' ? carrierTourId : focusOffer?.tour_id ?? null
  const mapTours = role === 'shipper' && !focusOffer ? [] : tourList ?? []

  return (
    <div className="v2">
      <div className="v2-map">
        <NetworkMap
          light
          chrome={false}
          showNetwork={false}
          pad={PAD[role]}
          network={network.data}
          error={network.error}
          selected={city}
          onSelect={(c) => {
            setCity({ city: c.city, state: c.state })
            setDrawer('city')
          }}
          filled={[]}
          greenLens={false}
          tours={mapTours}
          focusTourId={focusTourId}
          onSelectTour={(id) => {
            setRole('broker')
            setTourId(id)
          }}
          highlightLane={role === 'shipper' ? focusOffer?.lane ?? null : null}
        />
      </div>

      <div className="pill-surface v2-brand">
        <span className="logo">↺</span>
        <b>Return Trip</b>
        <small>{USE_MOCK ? 'demo data' : 'live'}</small>
      </div>

      <nav className="pill-surface v2-nav" aria-label="View as">
        {ROLES.map((r) => (
          <button key={r.id} className={role === r.id ? 'on' : ''} onClick={() => pickRole(r.id)}>
            {r.label}
          </button>
        ))}
      </nav>

      {role === 'broker' && (
        <div className="v2-actions">
          {['approvals', 'inbox', 'prices', 'agent'].map((d) => (
            <button key={d} className={`act ${drawer === d ? 'on' : ''}`} onClick={() => setDrawer(drawer === d ? null : d)}>
              {d === 'approvals' ? 'Approvals' : d === 'inbox' ? 'Inbox' : d === 'prices' ? 'Prices' : 'Ask agent'}
              {d === 'approvals' && pendingIds.length > 0 && <span className="n">{pendingIds.length}</span>}
            </button>
          ))}
          {MERIDIAN_WEB_URL && (
            <a className="act" href={MERIDIAN_WEB_URL} target="_blank" rel="noreferrer">Meridian ↗</a>
          )}
        </div>
      )}

      {/* ---------- broker: list on the left, selected loop at the bottom ---------- */}
      {role === 'broker' && (
        <>
          <aside className="float v2-left">
            <div className="scroll">
              <div className="kpi">
                <small>{money.unlocked > 0 ? 'Extra profit unlocked' : 'Extra profit waiting for you'}</small>
                <b>+{usd0(money.unlocked > 0 ? money.unlocked : money.waiting)}</b>
                <span>
                  {money.unlocked > 0 ? <>{usd0(money.waiting)} more waiting · </> : null}
                  <strong>{tourList?.length ?? 0} loops</strong>, trucks <strong>{money.loaded}% loaded</strong> instead of 50%
                </span>
              </div>
              {totals && (
                <div className="today">
                  Today Meridian books every load alone: trucks drive <b>{totals.empty_miles.toLocaleString()}</b> empty miles,
                  about <b>{usd0(totals.empty_cost_usd)}</b> lost.
                </div>
              )}
              <span className="list-title">Loops the brain built</span>
              <TourList tours={tourList} selectedId={tourId} onSelect={setTourId} />
            </div>
          </aside>

          {tour && !drawer && (
            <section className="float v2-bottom">
              <TourDetail
                key={tour.tour_id}
                tour={tour}
                pendingActionIds={pendingIds}
                priceLanes={priceLanes}
                onBooked={refreshAll}
                onToast={toast}
              />
            </section>
          )}
        </>
      )}

      {/* ---------- carrier: the driver's phone ---------- */}
      {role === 'carrier' && (
        <>
          <div className="float v2-note">
            <h3>What the carrier sees</h3>
            <p>
              Instead of one load and a drive home empty, the carrier gets a full week that ends at home. They take a bit
              less per load, and earn more per mile.
            </p>
          </div>
          <div className="v2-phone">
            <CarrierWeek
              weeks={weeks.data?.items ?? null}
              selectedId={carrierTourId}
              onSelect={setCarrierTourId}
              onResponded={refreshAll}
              onToast={toast}
            />
          </div>
        </>
      )}

      {/* ---------- manufacturer: offers on the left ---------- */}
      {role === 'shipper' && (
        <aside className="float v2-left wide">
          <div className="scroll">
            <ShipperOffers
              offers={offers.data?.items ?? null}
              selectedShipper={shipperId}
              onSelectShipper={setShipperId}
              onFocus={setFocusOffer}
              onResponded={() => offers.refresh()}
              onToast={toast}
            />
          </div>
        </aside>
      )}

      {/* ---------- secondary screens slide in from the right ---------- */}
      {drawer && (
        <aside className="float v2-drawer">
          <header>
            <b>{drawer === 'city' && city ? `${city.city}, ${city.state}` : DRAWERS[drawer]}</b>
            <button className="close" onClick={() => setDrawer(null)} aria-label="Close">✕</button>
          </header>
          <div className={`body ${drawer === 'agent' ? 'flush' : ''}`}>
            {drawer === 'approvals' && <ApprovalQueue pending={pending} onApproved={refreshAll} onToast={toast} />}
            {drawer === 'inbox' && <InboxPanel onToast={toast} onActionsCreated={() => pending.refresh()} />}
            {drawer === 'prices' && <PriceSignals />}
            {drawer === 'agent' && <AgentChat onError={(m) => toast(m, 'error')} />}
            {drawer === 'city' && (
              <CityPanel
                selected={city}
                network={network.data}
                queuedIds={(pending.data?.items ?? []).map((a) => a.prospect_id).filter(Boolean)}
                onSelect={(c) => setCity({ city: c.city, state: c.state })}
                onQueued={() => {
                  pending.refresh()
                  toast('Queued for approval', 'success')
                }}
                onError={(m) => toast(m, 'error')}
              />
            )}
          </div>
        </aside>
      )}

      <Toasts items={toasts} />
    </div>
  )
}
