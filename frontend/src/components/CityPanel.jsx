import { useEffect, useState } from 'react'
import { api } from '../api.js'
import ProspectCard from './ProspectCard.jsx'

function InOut({ inbound, outbound }) {
  return (
    <span className="inout">
      <span className={inbound === 0 ? 'zero' : ''}>{inbound}</span> in ·{' '}
      <span className={outbound === 0 ? 'zero' : ''}>{outbound}</span> out
    </span>
  )
}

function Skeletons({ count = 3, line = false }) {
  return Array.from({ length: count }, (_, i) => (
    <div key={i} className={`skeleton ${line ? 'line' : ''}`} />
  ))
}

// Top one-way cities by inbound volume. `.city-head` wrapper so `.zero` turns red.
function CityList({ network, onSelect, exclude }) {
  if (!network) return <div className="stack"><Skeletons count={4} line /></div>

  const cities = network.cities
    .filter((c) => c.one_way && !(exclude && c.city === exclude.city && c.state === exclude.state))
    .sort((a, b) => b.inbound - a.inbound)
    .slice(0, 8)

  return (
    <div className="stack city-head" style={{ gap: 8 }}>
      {cities.map((c) => (
        <button
          key={`${c.state}-${c.city}`}
          className="card row between"
          style={{ cursor: 'pointer', textAlign: 'left', width: '100%' }}
          onClick={() => onSelect(c)}
        >
          <b>{c.city}, {c.state}</b>
          <InOut inbound={c.inbound} outbound={c.outbound} />
        </button>
      ))}
    </div>
  )
}

export default function CityPanel({ selected, network, queuedIds = [], onSelect, onQueued, onError }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [queued, setQueued] = useState([])
  const [busy, setBusy] = useState(null)

  useEffect(() => {
    if (!selected) return
    let stale = false
    setData(null)
    setLoading(true)
    api
      .getCity(selected.state, selected.city)
      .then((d) => !stale && setData(d))
      .catch((e) => !stale && onError(e.message))
      .finally(() => !stale && setLoading(false))
    return () => {
      stale = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.city, selected?.state])

  async function fill(id) {
    setBusy(id)
    try {
      await api.fill(id)
      setQueued((q) => [...q, id])
      onQueued()
    } catch (e) {
      onError(e.message)
    } finally {
      setBusy(null)
    }
  }

  if (!selected) {
    return (
      <div>
        <h2 className="h2">Pick a city on the map</h2>
        <p className="muted">Red rings are one-way cities: trucks arrive full and leave empty. Start with the worst ones.</p>
        <div className="section-title">Top one-way cities</div>
        <CityList network={network} onSelect={onSelect} />
      </div>
    )
  }

  const prospects = [...(data?.prospects || [])].sort((a, b) => b.score - a.score)
  const compatible = prospects.filter((p) => p.ok)
  const blocked = prospects.filter((p) => !p.ok)

  const card = (p) => (
    <ProspectCard
      key={p.prospect_id}
      prospect={p}
      queued={queued.includes(p.prospect_id) || queuedIds.includes(p.prospect_id)}
      busy={busy === p.prospect_id}
      onFill={() => fill(p.prospect_id)}
    />
  )

  return (
    <div>
      {loading || !data ? (
        <div className="stack">
          <Skeletons count={3} line />
          <Skeletons count={3} />
        </div>
      ) : (
        <>
          <div className="city-head stack" style={{ gap: 6 }}>
            <h2 className="h2">{data.city}, {data.state}</h2>
            <InOut inbound={data.inbound} outbound={data.outbound} />
            <div className="muted">{data.summary}</div>
            {data.empty_trucks_next_7d != null && (
              <div className="small">{data.empty_trucks_next_7d} trucks empty out in the next 7 days</div>
            )}
          </div>

          {prospects.length === 0 ? (
            <div className="empty">No return loads found yet. {data.summary}</div>
          ) : (
            <>
              <div className="section-title">Compatible return loads ({compatible.length})</div>
              <div className="stack">{compatible.map(card)}</div>

              {blocked.length > 0 && (
                <>
                  <div className="section-title">Blocked by rules ({blocked.length})</div>
                  <p className="muted small">Shown on purpose so you can see why the agent said no.</p>
                  <div className="stack">{blocked.map(card)}</div>
                </>
              )}
            </>
          )}
        </>
      )}

      <div className="section-title">Other one-way cities</div>
      <CityList network={network} onSelect={onSelect} exclude={selected} />
    </div>
  )
}
