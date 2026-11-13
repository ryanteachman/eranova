import { useCallback, useMemo, useState } from 'react'
import { api, USE_MOCK } from '../api.js'
import usePoll from '../usePoll.js'
import TopBar from '../components/TopBar.jsx'
import NetworkMap from '../components/NetworkMap.jsx'
import TourBoard from '../components/TourBoard.jsx'
import CityPanel from '../components/CityPanel.jsx'
import PriceSignals from '../components/PriceSignals.jsx'
import ApprovalQueue from '../components/ApprovalQueue.jsx'
import InboxPanel from '../components/InboxPanel.jsx'
import AgentChat from '../components/AgentChat.jsx'
import CarrierWeek from '../components/CarrierWeek.jsx'
import ShipperOffers from '../components/ShipperOffers.jsx'
import MeridianFrame from '../components/MeridianFrame.jsx'
import Toasts from '../components/Toasts.jsx'

const BROKER_TABS = ['Tours', 'Prices', 'City', 'Approvals', 'Inbox', 'Agent']

export default function App() {
  const [role, setRole] = useState('broker') // broker | carrier | shipper
  const [tab, setTab] = useState('Tours')
  const [city, setCity] = useState(null)
  const [tourId, setTourId] = useState('T-101')
  const [carrierTourId, setCarrierTourId] = useState('T-101')
  const [shipperId, setShipperId] = useState(null)
  const [focusOffer, setFocusOffer] = useState(null)
  const [split, setSplit] = useState(false)
  const [greenLens, setGreenLens] = useState(false)
  const [filled, setFilled] = useState([]) // approved single return trips: { lane, miles }
  const [toasts, setToasts] = useState([])

  const network = usePoll(() => api.getNetwork(), 0)
  const pending = usePoll(() => api.getActions('pending'), 3000)
  const tours = usePoll(() => api.getTours(), 4000)
  const weeks = usePoll(() => api.getCarrierWeeks(), 4000)
  const offers = usePoll(() => api.getOffers(), 4000)

  const toast = useCallback((text, kind = 'info') => {
    const id = Math.random()
    setToasts((t) => [...t, { id, text, kind }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500)
  }, [])

  function selectCity(c) {
    setCity({ city: c.city, state: c.state })
    setRole('broker')
    setTab('City')
  }

  function handleApproved(action) {
    const result = action.result || {}
    if (result.lane) setFilled((f) => [...f, { lane: result.lane, miles: result.miles || 0 }])
    pending.refresh()
    tours.refresh()
    weeks.refresh()
  }

  const tourList = tours.data?.items ?? []
  const booked = tourList.filter((t) => t.status === 'booked')
  const stats = useMemo(
    () => ({
      profitUnlocked: booked.reduce((s, t) => s + t.totals.profit_unlocked, 0),
      profitAvailable: tourList.reduce((s, t) => s + t.totals.profit_unlocked, 0),
      tourMilesSaved: booked.reduce((s, t) => s + (t.totals.standalone_empty_miles - t.totals.empty_miles), 0),
    }),
    [tours.data], // eslint-disable-line react-hooks/exhaustive-deps
  )
  const filledMiles = filled.reduce((sum, f) => sum + f.miles, 0) + stats.tourMilesSaved
  const pendingIds = (pending.data?.items ?? []).map((a) => a.action_id)
  const pendingCount = pendingIds.length

  // What the map focuses on depends on who is looking.
  let focusTourId = null
  let highlightLane = null
  let hint = null
  if (role === 'broker' && tab === 'Tours') {
    focusTourId = tourId
    hint = 'The brain chains real Meridian loads into loops. Pink legs are the ones it found to close the loop.'
  } else if (role === 'carrier') {
    focusTourId = carrierTourId
    hint = 'One truck, one week, never idle: it drives the loop and ends at home.'
  } else if (role === 'shipper') {
    focusTourId = focusOffer?.tour_id ?? null
    highlightLane = focusOffer?.lane ?? null
    hint = 'Shippers fill trucks that are already nearby, or move a date to close a loop and save.'
  }
  const showTours = role !== 'broker' || tab === 'Tours'

  return (
    <div className="app">
      <TopBar
        role={role}
        onRole={(r) => {
          setRole(r)
          if (r === 'broker') setTab('Tours')
        }}
        totals={network.data?.totals}
        filledMiles={filledMiles}
        filledCount={filled.length + booked.length}
        profitUnlocked={stats.profitUnlocked}
        profitAvailable={stats.profitAvailable}
        split={split}
        onSplit={() => setSplit((s) => !s)}
        greenLens={greenLens}
        onGreen={() => setGreenLens((g) => !g)}
        live={!USE_MOCK}
      />

      <div className={`main ${split ? 'split' : ''}`}>
        <div className="left">
          {split ? (
            <MeridianFrame />
          ) : (
            <NetworkMap
              network={network.data}
              error={network.error}
              selected={city}
              onSelect={selectCity}
              filled={filled}
              greenLens={greenLens}
              tours={showTours ? tourList : []}
              focusTourId={focusTourId}
              onSelectTour={(id) => {
                setTourId(id)
                setRole('broker')
                setTab('Tours')
              }}
              highlightLane={highlightLane}
              hint={hint}
            />
          )}
        </div>

        <div className="right">
          {role === 'broker' && (
            <>
              <nav className="tabs">
                {BROKER_TABS.map((t) => (
                  <button key={t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
                    {t}
                    {t === 'Approvals' && pendingCount > 0 && <span className="badge-count">{pendingCount}</span>}
                  </button>
                ))}
              </nav>

              {tab === 'Tours' && (
                <div className="tab-body">
                  <TourBoard
                    tours={tours.data ? tourList : null}
                    selectedId={tourId}
                    onSelect={setTourId}
                    pendingActionIds={pendingIds}
                    onBooked={handleApproved}
                    onToast={toast}
                  />
                </div>
              )}
              {tab === 'Prices' && (
                <div className="tab-body">
                  <PriceSignals />
                </div>
              )}
              {tab === 'City' && (
                <div className="tab-body">
                  <CityPanel
                    selected={city}
                    network={network.data}
                    queuedIds={(pending.data?.items ?? []).map((a) => a.prospect_id).filter(Boolean)}
                    onSelect={selectCity}
                    onQueued={() => {
                      pending.refresh()
                      toast('Queued for approval', 'success')
                    }}
                    onError={(m) => toast(m, 'error')}
                  />
                </div>
              )}
              {tab === 'Approvals' && (
                <div className="tab-body">
                  <ApprovalQueue pending={pending} onApproved={handleApproved} onToast={toast} />
                </div>
              )}
              {tab === 'Inbox' && (
                <div className="tab-body">
                  <InboxPanel onToast={toast} onActionsCreated={() => pending.refresh()} />
                </div>
              )}
              {tab === 'Agent' && (
                <div className="tab-body flush">
                  <AgentChat onError={(m) => toast(m, 'error')} />
                </div>
              )}
            </>
          )}

          {role === 'carrier' && (
            <div className="tab-body">
              <CarrierWeek
                weeks={weeks.data?.items ?? null}
                selectedId={carrierTourId}
                onSelect={setCarrierTourId}
                onResponded={() => {
                  weeks.refresh()
                  tours.refresh()
                }}
                onToast={toast}
              />
            </div>
          )}

          {role === 'shipper' && (
            <div className="tab-body">
              <ShipperOffers
                offers={offers.data?.items ?? null}
                selectedShipper={shipperId}
                onSelectShipper={setShipperId}
                onFocus={setFocusOffer}
                onResponded={() => offers.refresh()}
                onToast={toast}
              />
            </div>
          )}
        </div>
      </div>

      <Toasts items={toasts} />
    </div>
  )
}
