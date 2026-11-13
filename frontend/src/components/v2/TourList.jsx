const usd0 = (n) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const EQ = { V: 'Dry van', R: 'Reefer', F: 'Flatbed' }

// "Grand Rapids → Columbus → Fort Worth → Dallas → Chicago"
export function routeText(tour) {
  const cities = []
  tour.legs.forEach((l) => {
    if (cities[cities.length - 1] !== l.origin.city) cities.push(l.origin.city)
    cities.push(l.destination.city)
  })
  return cities.filter((c, i) => c !== cities[i - 1]).join(' → ')
}

export default function TourList({ tours, selectedId, onSelect }) {
  if (!tours) return [0, 1, 2].map((i) => <div key={i} className="skeleton" />)
  return tours.map((t) => {
    const found = t.legs.filter((l) => l.kind === 'new').length
    const booked = t.status === 'booked'
    return (
      <button key={t.tour_id} className={`tour-item ${t.tour_id === selectedId ? 'on' : ''}`} onClick={() => onSelect(t.tour_id)}>
        <div className="row between">
          <span className="row" style={{ gap: 8 }}>
            <span className="dot" style={{ background: t.color }} />
            <span className="meta">{t.carrier.name} · {EQ[t.equipment] ?? t.equipment}</span>
          </span>
          <span className={`status ${booked ? 'booked' : 'ready'}`}>{booked ? 'Booked' : 'Ready to book'}</span>
        </div>
        <span className="route">{routeText(t)}</span>
        <div className="foot">
          <span className="meta">
            {t.totals.loaded_pct}% loaded · {found} {found === 1 ? 'leg' : 'legs'} found by the brain
          </span>
          <span className="gain">+{usd0(t.totals.profit_unlocked)}</span>
        </div>
      </button>
    )
  })
}
