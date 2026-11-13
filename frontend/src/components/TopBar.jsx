import EmptyCounter from './EmptyCounter.jsx'

const ROLES = [
  { id: 'broker', label: 'Broker' },
  { id: 'carrier', label: 'Carrier' },
  { id: 'shipper', label: 'Manufacturer' },
]

const usd = (n) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

export default function TopBar({
  role, onRole, totals, filledMiles, filledCount, profitUnlocked, profitAvailable,
  split, onSplit, greenLens, onGreen, live,
}) {
  return (
    <header className="topbar">
      <div className="brand">
        <b>Return<span>Trip</span></b>
        <small>
          {totals ? `${totals.loads} Meridian loads · ${totals.one_way_cities} one-way cities` : 'Loading network…'}
        </small>
      </div>

      <div className="roles" role="tablist" aria-label="View as">
        {ROLES.map((r) => (
          <button key={r.id} className={`role ${role === r.id ? 'on' : ''}`} onClick={() => onRole(r.id)}>
            {r.label}
          </button>
        ))}
      </div>

      <EmptyCounter totals={totals} filledMiles={filledMiles} filledCount={filledCount} greenLens={greenLens} />

      {profitAvailable > 0 && (
        <div className="profit">
          <b className="num">+{usd(profitUnlocked)}</b>
          <small>profit unlocked · {usd(profitAvailable - profitUnlocked)} waiting</small>
        </div>
      )}

      <div className="spacer" />

      <div className="toggles">
        <button className={`toggle ${greenLens ? 'on green' : ''}`} onClick={onGreen}>
          Green
        </button>
        <button className={`toggle ${split ? 'on' : ''}`} onClick={onSplit}>
          {split ? 'Map' : 'Meridian'}
        </button>
      </div>

      <span className={`mode-pill ${live ? 'live' : ''}`}>{live ? 'Live API' : 'Mock data'}</span>
    </header>
  )
}
