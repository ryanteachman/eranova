import { useEffect, useRef, useState } from 'react'

const KG_CO2_PER_EMPTY_MILE = 1.46 // diesel ~10.2 kg CO2/gal at ~7 mpg empty; an estimate

// Animates from the last shown value to `target` (count up on load, tick down on fill).
function useTween(target, ms = 1500) {
  const [value, setValue] = useState(0)
  const from = useRef(0)

  useEffect(() => {
    if (target == null) return undefined
    const start = performance.now()
    const begin = from.current
    let frame
    const step = (now) => {
      const t = Math.min(1, (now - start) / ms)
      const eased = 1 - Math.pow(1 - t, 3)
      const v = begin + (target - begin) * eased
      setValue(v)
      from.current = v
      if (t < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [target, ms])

  return value
}

export default function EmptyCounter({ totals, filledMiles, filledCount, greenLens }) {
  const perMile = totals?.cost_per_empty_mile ?? 2
  const miles = totals ? Math.max(0, totals.empty_miles - filledMiles) : null
  const shownMiles = useTween(miles)
  const shownCost = useTween(miles == null ? null : miles * perMile)
  const shownCo2 = useTween(miles == null ? null : (miles * KG_CO2_PER_EMPTY_MILE) / 1000)

  return (
    <div className="counter">
      <div className="stat">
        <b>{Math.round(shownMiles).toLocaleString()}</b>
        <small>empty miles</small>
      </div>
      <div className="stat money">
        <b>${Math.round(shownCost).toLocaleString()}</b>
        <small>lost driving home empty</small>
      </div>
      {greenLens && (
        <div className="stat">
          <b style={{ color: 'var(--success)' }}>{shownCo2.toFixed(1)} t</b>
          <small>CO₂ from empty miles (est.)</small>
        </div>
      )}
      {filledCount > 0 && (
        <span className="saved">
          ▼ {filledMiles.toLocaleString()} mi filled · {filledCount} return {filledCount === 1 ? 'trip' : 'trips'}
        </span>
      )}
    </div>
  )
}
