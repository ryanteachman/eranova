import { useEffect, useMemo, useRef } from 'react'
import L from 'leaflet'
import { CircleMarker, MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet'

const EQUIPMENT_COLORS = { V: '#22d3ee', R: '#3b82f6', F: '#f59e0b' }
const OTHER_COLOR = '#a78bfa'
const GHOST_COUNT = 10
const GHOST_SECONDS = 9

const truckIcon = L.divIcon({ className: 'ghost-truck', html: '🚚', iconSize: [20, 20] })
const loopTruckIcon = L.divIcon({ className: 'loop-truck', html: '🚛', iconSize: [26, 26] })
const LEG_STYLE = {
  missing: { color: '#db2777', weight: 4, dashArray: '10 10', className: 'leg-missing' },
  quoted: { color: '#22c55e', weight: 5 },
  empty: { color: '#8b98ad', weight: 2, dashArray: '2 7', opacity: 0.8 },
}
const MONO_STYLE = {
  missing: { color: '#2541ff', weight: 4, dashArray: '9 9', className: 'leg-missing' },
  quoted: { color: '#2541ff', weight: 4 },
  empty: { color: '#9ca3af', weight: 2, dashArray: '2 7' },
}
const legNumIcon = (n, color) =>
  L.divIcon({ className: 'leg-num', html: `<span style="border-color:${color}">${n}</span>`, iconSize: [20, 20] })

// ~30 points on a quadratic Bézier between two places, bent to the left of travel.
function curve(a, b, bend = 0.18, n = 30) {
  const dLat = b.lat - a.lat
  const dLng = b.lng - a.lng
  const ctrl = [(a.lat + b.lat) / 2 + bend * dLng, (a.lng + b.lng) / 2 - bend * dLat]
  const pts = []
  for (let i = 0; i <= n; i++) {
    const t = i / n
    const u = 1 - t
    pts.push([
      u * u * a.lat + 2 * u * t * ctrl[0] + t * t * b.lat,
      u * u * a.lng + 2 * u * t * ctrl[1] + t * t * b.lng,
    ])
  }
  return pts
}

function pointAt(pts, t) {
  const f = t * (pts.length - 1)
  const i = Math.min(pts.length - 2, Math.floor(f))
  const k = f - i
  return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * k, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * k]
}

const same = (p, q) => p.city === q.city && p.state === q.state

function arcColor(arc, greenLens, maxEmpty) {
  if (greenLens) {
    const heat = maxEmpty ? arc.empty_miles / maxEmpty : 0
    return heat > 0.5 ? '#ef4444' : heat > 0.15 ? '#f59e0b' : '#22c55e'
  }
  return EQUIPMENT_COLORS[arc.dominant_equipment] || OTHER_COLOR
}

// Shrinks panel padding on small screens so the route never gets squeezed to nothing.
function fitPad(map, pad) {
  if (!pad.paddingTopLeft) return pad
  const { x, y } = map.getSize()
  const [l, t] = pad.paddingTopLeft
  const [r, b] = pad.paddingBottomRight
  const kx = Math.min(1, (x * 0.6) / (l + r))
  const ky = Math.min(1, (y * 0.6) / (t + b))
  return { paddingTopLeft: [l * kx, t * ky], paddingBottomRight: [r * kx, b * ky] }
}

// Zooms the map to the whole network once, so it frames well at any screen size.
function FitToNetwork({ cities, pad }) {
  const map = useMap()
  const done = useRef(false)
  useEffect(() => {
    if (done.current || cities.length === 0) return
    map.fitBounds(cities.map((c) => [c.lat, c.lng]), fitPad(map, pad))
    done.current = true
  }, [cities, map])
  return null
}

// Flies to a tour's legs whenever the focused tour changes.
function FlyToTour({ tour, pad }) {
  const map = useMap()
  useEffect(() => {
    if (!tour) return
    const pts = tour.legs.flatMap((l) => [[l.origin.lat, l.origin.lng], [l.destination.lat, l.destination.lng]])
    map.flyToBounds(pts, { ...fitPad(map, pad), duration: 0.8, maxZoom: 5.5 })
  }, [tour?.tour_id, JSON.stringify(pad), map]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

// Every leg of every tour, plus a loaded truck that drives the focused loop without stopping.
function TourLayer({ tours, focusId, onSelectTour, pad, mono }) {
  const truck = useRef(null)
  const focus = tours.find((t) => t.tour_id === focusId)
  const loopPath = useMemo(
    () => (focus ? focus.legs.flatMap((l) => curve(l.origin, l.destination, l.kind === 'empty' ? 0.05 : 0.12, 24)) : []),
    [focus],
  )

  useEffect(() => {
    if (loopPath.length < 2) return undefined
    let frame
    const tick = (now) => {
      truck.current?.setLatLng(pointAt(loopPath, (now / 1000 / 14) % 1))
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [loopPath])

  return (
    <>
      {(mono ? tours.filter((t) => t.tour_id === focusId) : tours).map((t) => {
        const isFocus = t.tour_id === focusId
        const faded = focusId && !isFocus
        return t.legs.map((l) => {
          const pts = curve(l.origin, l.destination, l.kind === 'empty' ? 0.05 : 0.12)
          const style = (mono ? MONO_STYLE[l.status] : LEG_STYLE[l.status]) || { color: mono ? '#111827' : t.color, weight: 4 }
          const opacity = faded ? 0.18 : style.opacity ?? 1
          const mid = pts[Math.floor(pts.length / 2)]
          return (
            <span key={`${t.tour_id}-${l.seq}`}>
              {l.kind !== 'empty' && !mono && (
                <Polyline positions={pts} pathOptions={{ color: style.color, weight: style.weight + 8, opacity: faded ? 0.04 : 0.16 }} />
              )}
              {mono && l.kind !== 'empty' && [l.origin, l.destination].map((p, k) => (
                <CircleMarker key={k} center={[p.lat, p.lng]} radius={7} interactive={false}
                  pathOptions={{ color: '#111827', weight: 2.5, fillColor: '#ffffff', fillOpacity: 1 }} />
              ))}
              <Polyline
                positions={pts}
                pathOptions={{ ...style, opacity, lineCap: 'round' }}
                eventHandlers={{ click: () => onSelectTour(t.tour_id) }}
              >
                <Tooltip className="city-tip" sticky>
                  {t.tour_id} · leg {l.seq}: {l.origin.city} → {l.destination.city} · {l.miles} mi
                  <br />
                  {l.kind === 'empty' ? l.note : `${l.customer} · ${l.status.replace('_', ' ')}`}
                </Tooltip>
              </Polyline>
              {isFocus && !mono && l.kind !== 'empty' && <Marker position={mid} icon={legNumIcon(l.seq, style.color)} interactive={false} />}
            </span>
          )
        })
      })}
      {focus && loopPath.length > 1 && (
        <Marker position={loopPath[0]} icon={loopTruckIcon} ref={truck}>
          <Tooltip className="city-tip">
            {focus.carrier.name}: {focus.totals.loaded_pct}% loaded, home by {focus.window.home_by}
          </Tooltip>
        </Marker>
      )}
      <FlyToTour tour={focus} pad={pad} />
    </>
  )
}

// Moves the ghost-truck markers along their return paths without re-rendering React.
function useGhostAnimation(ghosts, markers) {
  useEffect(() => {
    let frame
    const tick = (now) => {
      ghosts.forEach((g, i) => {
        const m = markers.current[g.id]
        if (!m) return
        const t = ((now / 1000 / GHOST_SECONDS) + i / ghosts.length) % 1
        m.setLatLng(pointAt(g.path, t))
      })
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [ghosts, markers])
}

export default function NetworkMap({
  network, error, selected, onSelect, filled, greenLens,
  tours = [], focusTourId = null, onSelectTour = () => {}, highlightLane = null, hint = null,
  light = false, showNetwork = true, chrome = true, pad = { padding: [40, 40] }, showCities = true, mono = false,
}) {
  const dim = tours.length > 0
  const markers = useRef({})
  const arcs = network?.arcs ?? []
  const cities = network?.cities ?? []
  const maxEmpty = Math.max(0, ...arcs.map((a) => a.empty_miles))

  const isFilled = (arc) =>
    filled.some((f) => same(f.lane.origin, arc.destination) && same(f.lane.destination, arc.origin))

  // Return paths (destination -> origin) for the busiest one-way arcs that are still empty.
  const ghosts = useMemo(
    () =>
      arcs
        .filter((a) => a.reverse_loads === 0 && !isFilled(a))
        .slice(0, GHOST_COUNT)
        .map((a) => ({ id: a.id, path: curve(a.destination, a.origin) })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [arcs, filled],
  )
  useGhostAnimation(ghosts, markers)

  const labelled = cities.filter((c) => c.inbound >= 15)

  return (
    <>
      <MapContainer className="map" center={[38.2, -97]} zoom={4.5} minZoom={3} zoomSnap={0.25} worldCopyJump>
        {/* CARTO Dark Matter now needs an API key, so we use Esri's keyless gray canvases. */}
        <TileLayer
          key={light ? 'light' : 'dark'}
          url={`https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_${light ? 'Light' : 'Dark'}_Gray_Base/MapServer/tile/{z}/{y}/{x}`}
          attribution="Tiles &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors"
          maxZoom={16}
        />
        <FitToNetwork cities={cities} pad={pad} />

        {showNetwork && arcs.map((arc) => {
          const pts = curve(arc.origin, arc.destination)
          const color = arcColor(arc, greenLens, maxEmpty)
          const weight = Math.min(9, 1.5 + arc.loads * 0.28)
          return (
            <span key={arc.id}>
              <Polyline positions={pts} pathOptions={{ color, weight: weight + 7, opacity: dim ? 0.04 : 0.12, lineCap: 'round' }} />
              <Polyline positions={pts} pathOptions={{ color, weight, opacity: dim ? 0.22 : 0.85, lineCap: 'round' }}>
                <Tooltip className="city-tip" sticky>
                  {arc.origin.city} → {arc.destination.city} · {arc.loads} loads · {arc.reverse_loads} back
                  <br />
                  {arc.commodities[0]}
                </Tooltip>
              </Polyline>
            </span>
          )
        })}

        {!dim && ghosts.map((g) => (
          <Polyline key={`${g.id}-dash`} positions={g.path} pathOptions={{ color: '#8b98ad', weight: 1.5, opacity: 0.5, dashArray: '4 6' }} />
        ))}

        {filled.map((f, i) => {
          const pts = curve(f.lane.origin, f.lane.destination)
          return (
            <span key={`filled-${i}`}>
              <Polyline positions={pts} pathOptions={{ color: '#22c55e', weight: 14, opacity: 0.18 }} />
              <Polyline positions={pts} pathOptions={{ color: '#22c55e', weight: 4, opacity: 1 }}>
                <Tooltip className="city-tip" sticky>
                  Return trip filled: {f.lane.origin.city} → {f.lane.destination.city}
                </Tooltip>
              </Polyline>
            </span>
          )
        })}

        {highlightLane && (
          <Polyline
            positions={curve(highlightLane.origin, highlightLane.destination, 0.12)}
            pathOptions={{ color: light ? '#d97706' : '#f8fafc', weight: 16, opacity: light ? 0.25 : 0.18, lineCap: 'round' }}
          />
        )}

        {tours.length > 0 && <TourLayer tours={tours} focusId={focusTourId} onSelectTour={onSelectTour} pad={pad} mono={mono} />}

        {!dim && ghosts.map((g) => (
          <Marker
            key={g.id}
            position={g.path[0]}
            icon={truckIcon}
            interactive
            ref={(m) => {
              if (m) markers.current[g.id] = m
              else delete markers.current[g.id]
            }}
          >
            <Tooltip className="city-tip">EMPTY · driving home with nothing</Tooltip>
          </Marker>
        ))}

        {showCities && cities.map((c) => {
          const isSel = selected && same(selected, c)
          const label = labelled.includes(c)
          return (
            <CircleMarker
              key={c.id}
              center={[c.lat, c.lng]}
              radius={4 + Math.sqrt(c.inbound) * 1.8}
              pathOptions={{
                color: isSel ? '#22d3ee' : c.one_way ? '#ef4444' : '#3b4a66',
                weight: isSel ? 3.5 : 2,
                fillColor: c.one_way ? (light ? '#ffffff' : '#1f2937') : '#22d3ee',
                fillOpacity: c.one_way ? 0.9 : 0.6,
              }}
              eventHandlers={{ click: () => onSelect(c) }}
            >
              <Tooltip
                className={label ? 'city-label' : 'city-tip'}
                permanent={label}
                direction={label ? 'right' : 'top'}
                offset={label ? [8, 0] : [0, -6]}
              >
                {c.city}, {c.state} · {c.inbound} in ·{' '}
                <span className={c.outbound === 0 ? 'out0' : ''}>{c.outbound} out</span>
              </Tooltip>
            </CircleMarker>
          )
        })}
      </MapContainer>

      {!chrome ? null : hint ? (
        <div className="map-hint">{hint}</div>
      ) : !selected && (
        <div className="map-hint">
          {error ? (
            <span style={{ color: 'var(--danger)' }}>{error}</span>
          ) : network ? (
            <>
              Freight only flows one way. <b>Click a red-ringed city</b> to fill the trip home.
            </>
          ) : (
            'Loading the Meridian network…'
          )}
        </div>
      )}

      {chrome && <div className="legend">
        {dim ? (
          <>
            <span><i style={{ background: '#22d3ee' }} />Booked leg</span>
            <span><i style={{ background: 'repeating-linear-gradient(90deg,#f472b6 0 5px,transparent 5px 9px)' }} />Missing leg (agent found)</span>
            <span><i style={{ background: '#22c55e' }} />Leg filled</span>
            <span><i className="dash" />Short empty hop</span>
            <span><i className="ring" style={{ width: 10, height: 10 }} />Ships nothing out</span>
          </>
        ) : (
          <>
            <span><i style={{ background: EQUIPMENT_COLORS.V }} />Dry van</span>
            <span><i style={{ background: EQUIPMENT_COLORS.R }} />Reefer</span>
            <span><i style={{ background: EQUIPMENT_COLORS.F }} />Flatbed</span>
            <span><i className="dash" />Empty trip home</span>
            <span><i style={{ background: '#22c55e' }} />Filled return trip</span>
            <span><i className="ring" style={{ width: 10, height: 10 }} />Ships nothing out</span>
          </>
        )}
      </div>}
    </>
  )
}
