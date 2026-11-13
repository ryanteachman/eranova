import { useEffect, useMemo, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { MapboxOverlay } from '@deck.gl/mapbox'
import { ArcLayer, PathLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers'
import { TripsLayer } from '@deck.gl/geo-layers'
import { PathStyleExtension } from '@deck.gl/extensions'
import './Map3D.css'

const STYLE = 'https://tiles.openfreemap.org/styles/positron'
const DEM = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'
// Keep the map close to north-up so it reads like a map, not a fly-through.
const BEARING = -6
const SWAY_DEG = 3
const START = { center: [-96, 38.5], zoom: 3.6, pitch: 45, bearing: BEARING }

const INK = [17, 24, 39]
const BLUE = [37, 65, 255]
const GREY = [156, 163, 175]
// One colour per state, used everywhere (map, cards, legend).
export const STATUS_RGB = { booked: [22, 163, 74], ready: [217, 119, 6], found: BLUE }
const tourState = (t) => (t.status === 'booked' ? 'booked' : 'ready')
// a leg the brain found that is not booked yet is blue; everything else takes its loop's colour
const legRgb = (t, l) => l.rgb ?? (l.status === 'missing' ? STATUS_RGB.found : STATUS_RGB[tourState(t)])
const LOOP = 12 // seconds per lap, focused tour
const IDLE_MS = 6000
const ORBIT_DEG_S = 2
const NO_PAD = { top: 0, right: 0, bottom: 0, left: 0 }

const hexRgb = (hex) => {
  const n = parseInt(String(hex || '#9ca3af').replace('#', ''), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}
const ll = (p) => [p.lng, p.lat]
const rad = Math.PI / 180

// Great-circle samples between two stops, plus the arc length in radians.
function greatCircle(a, b, n = 32) {
  const [l1, p1, l2, p2] = [a.lng * rad, a.lat * rad, b.lng * rad, b.lat * rad]
  const d = 2 * Math.asin(Math.sqrt(Math.sin((p2 - p1) / 2) ** 2 +
    Math.cos(p1) * Math.cos(p2) * Math.sin((l2 - l1) / 2) ** 2))
  if (d < 1e-9) return { pts: [ll(a), ll(b)], d: 0 }
  const pts = []
  for (let i = 0; i <= n; i++) {
    const f = i / n
    const A = Math.sin((1 - f) * d) / Math.sin(d)
    const B = Math.sin(f * d) / Math.sin(d)
    const x = A * Math.cos(p1) * Math.cos(l1) + B * Math.cos(p2) * Math.cos(l2)
    const y = A * Math.cos(p1) * Math.sin(l1) + B * Math.cos(p2) * Math.sin(l2)
    const z = A * Math.sin(p1) + B * Math.sin(p2)
    pts.push([Math.atan2(y, x) / rad, Math.atan2(z, Math.hypot(x, y)) / rad])
  }
  return { pts, d }
}

// Real road geometry when the leg has it (OSRM routes in the mock data), otherwise a great circle.
function roadPath(l) {
  if (Array.isArray(l.path) && l.path.length > 1) {
    const pts = l.path
    let d = 0
    for (let i = 1; i < pts.length; i++) {
      const k = Math.cos(((pts[i][1] + pts[i - 1][1]) / 2) * rad)
      d += Math.hypot((pts[i][0] - pts[i - 1][0]) * k, pts[i][1] - pts[i - 1][1]) * rad
    }
    return { pts, d }
  }
  return greatCircle(l.origin, l.destination)
}

const EMPTY_RGB = [220, 38, 38] // empty drives are red everywhere: the line and the truck on it

// One truck going round a tour's legs: 3 laps so the trail never pops at the wrap.
// Each point carries its own colour, so the truck turns red while it drives empty.
function buildTrip(tour, period, offset, color) {
  if (tour.kind === 'hub') {
    return (tour.legs || []).flatMap((l) => buildTrip({ ...tour, kind: 'leg', legs: [l] }, period, offset, l.rgb ? [...l.rgb, 255] : color) || [])
  }
  const legs = [...(tour.legs || [])].sort((a, b) => a.seq - b.seq)
  const segs = legs.map(roadPath)
  const total = segs.reduce((s, g) => s + g.d, 0)
  if (!total) return null
  const alpha = color[3] ?? 255
  // One trip per lap: a route that doesn't end where it started (a one-way lane) must not draw
  // a straight line from its end back to its start between laps.
  const laps = []
  for (let lap = 0; lap < 3; lap++) {
    const path = []
    const timestamps = []
    const colors = []
    let run = 0
    segs.forEach((g, li) => {
      const c = legs[li].kind === 'empty' ? [...EMPTY_RGB, alpha] : color
      g.pts.forEach((p, i) => {
        if (i === 0 && path.length) return
        path.push(p)
        colors.push(c)
        timestamps.push(lap * period + ((run + (g.d * i) / (g.pts.length - 1)) / total) * period - offset)
      })
      run += g.d
    })
    laps.push({ tour_id: tour.tour_id, path, timestamps, color, colors })
  }
  return laps
}

// Hub and spoke: arcs from the plant (width = loads since January), sized destination nodes, the plant as a dark hub, and live trucks
// at the city they last reported from (Meridian check calls).
function hubLayers(h, sec, pulse) {
  const font = { fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif', fontWeight: 600, characterSet: 'auto', background: true,
    getBackgroundColor: [255, 255, 255, 235], backgroundPadding: [6, 3], getBorderColor: [...INK, 40], getBorderWidth: 1 }
  return [
    // spokes as arcs (like the loops): faint at the plant, full colour where the goods arrive
    new ArcLayer({
      id: 'hub-spokes', data: h.spokes, getSourcePosition: (x) => x.path[0], getTargetPosition: (x) => x.path[1],
      getSourceColor: (x) => [x.color[0], x.color[1], x.color[2], 90], getTargetColor: (x) => x.color,
      getWidth: (x) => x.width, getHeight: 0.4, greatCircle: false,
    }),
    new ScatterplotLayer({ id: 'hub-nodes', data: h.nodes, getPosition: (x) => x.pos, radiusUnits: 'pixels', getRadius: (x) => x.radius, getFillColor: (x) => [...x.color, 255], stroked: true, getLineColor: [255, 255, 255], lineWidthUnits: 'pixels', getLineWidth: 3 }),
    new TextLayer({ id: 'hub-node-labels', data: h.nodes, getPosition: (x) => x.pos, getText: (x) => x.label, getSize: 12, getColor: INK, getPixelOffset: (x) => [0, -x.radius - 14], ...font }),
    new ScatterplotLayer({ id: 'hub-halo', data: h.centre, getPosition: (x) => x.pos, radiusUnits: 'pixels', getRadius: 26 + pulse * 10, getFillColor: [...INK, Math.round(40 * (1 - pulse) + 15)], updateTriggers: { getRadius: pulse, getFillColor: pulse } }),
    new ScatterplotLayer({ id: 'hub-centre', data: h.centre, getPosition: (x) => x.pos, radiusUnits: 'pixels', getRadius: 18, getFillColor: [...INK, 255], stroked: true, getLineColor: [255, 255, 255], lineWidthUnits: 'pixels', getLineWidth: 4 }),
    new TextLayer({ id: 'hub-centre-label', data: h.centre, getPosition: (x) => x.pos, getText: (x) => x.name, getSize: 14, getColor: INK, getPixelOffset: [0, 40], ...font }),
    new ScatterplotLayer({ id: 'hub-trucks', data: h.trucks, getPosition: (x) => x.pos, radiusUnits: 'pixels', getRadius: 7, getFillColor: (x) => (x.alert ? [...EMPTY_RGB, 255] : [217, 119, 6, 255]), stroked: true, getLineColor: [255, 255, 255], lineWidthUnits: 'pixels', getLineWidth: 2.5 }),
    new TextLayer({ id: 'hub-truck-labels', data: h.trucks, getPosition: (x) => x.pos, getText: (x) => x.label, getSize: 11, getColor: (x) => (x.alert ? EMPTY_RGB : INK), getPixelOffset: [0, 16], ...font }),
  ]
}

function legLabel(l) {
  const s = String(l.status || '').replace('_', ' ')
  return `${l.origin.city} → ${l.destination.city}${l.miles ? ` · ${l.miles} mi` : ''} · ${s}`
}

export default function Map3D({ tours = [], focusTourId = null, onSelectTour, pad = NO_PAD }) {
  const el = useRef(null)
  const mapRef = useRef(null)
  const overlayRef = useRef(null)
  const dataRef = useRef(null)
  const renderRef = useRef(() => {})
  const idleSince = useRef(0)
  const flownTo = useRef(null)
  const loaded = useRef(false)
  const flyRef = useRef(() => {})
  const onSelect = useRef(onSelectTour)
  onSelect.current = onSelectTour

  const reduced = useMemo(
    () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches,
    []
  )

  // ---- derived, static layer data (recomputed only when inputs change) ----
  const data = useMemo(() => {
    const focus = tours.find((t) => t.tour_id === focusTourId) || null
    const arcs = []       // every loaded leg of every loop: the overview
    const roads = []      // the focused loop on its real roads
    const roadsFound = [] // the focused loop's brain-found legs, dashed
    const empties = []
    // hub and spoke: one plant in the middle, straight spokes to everywhere it ships
    let hub = null
    if (focus?.kind === 'hub') {
      const centre = ll(focus.hub)
      const max = Math.max(1, ...focus.legs.map((l) => l.loads_all || 1))
      hub = {
        centre: [{ pos: centre, name: focus.name }],
        spokes: focus.legs.map((l) => ({
          tour_id: focus.tour_id, path: [centre, ll(l.destination)], color: [...l.rgb, 235],
          width: 3 + 9 * Math.sqrt((l.loads_all || 1) / max), loads: l.loads_all, live: l.loads_week > 0,
        })),
        nodes: focus.legs.map((l) => ({
          pos: ll(l.destination), color: l.rgb, radius: 6 + 10 * Math.sqrt((l.loads_all || 1) / max),
          label: `${l.destination.city} · ${l.loads_all} ${l.loads_all === 1 ? 'load' : 'loads'}`,
        })),
        trucks: (focus.trucks || []).map((t) => ({ ...t, pos: [t.lng, t.lat] })),
      }
    }
    for (const t of tours) {
      if (t.kind === 'hub' && hub) continue
      const isFocus = t === focus
      for (const l of t.legs || []) {
        const row = { ...l, tour_id: t.tour_id, src: ll(l.origin), dst: ll(l.destination), road: roadPath(l).pts }
        if (l.kind === 'empty') {
          if (isFocus) empties.push({ ...row, path: row.road })
          continue
        }
        // with a loop selected, everything else turns light grey so only the selection has colour
        const rgb = focus && !isFocus ? [203, 213, 225] : legRgb(t, l)
        // direction: the arc fades in from where the truck starts to where it arrives
        const a = isFocus ? 255 : focus ? 110 : 230
        // arcs show direction: the selected loop in its own colour, everything else light grey
        arcs.push({ ...row, from: [...rgb, Math.round(a * 0.25)], to: [...rgb, a], width: isFocus ? 4 : focus ? 2 : 3.5, focus: isFocus })
        if (isFocus) (l.status === 'missing' ? roadsFound : roads).push({ ...row, color: [...rgb, 255] })
      }
    }
    const truckRgb = focus ? (focus.status === 'lane' ? STATUS_RGB.found : STATUS_RGB[tourState(focus)]) : BLUE
    const tripsFocus = focus && !hub
      ? [0, LOOP / 2].flatMap((o) => buildTrip(focus, LOOP, o, [...truckRgb, 255]) || [])
      : []
    const stops = []
    const seen = new Set()
    for (const l of hub ? [] : focus?.legs || []) {
      for (const p of [l.origin, l.destination]) {
        const k = `${p.city}|${p.state}`
        if (!seen.has(k)) { seen.add(k); stops.push({ ...p, pos: ll(p) }) }
      }
    }
    return { focus, all: tours, arcs, roads, roadsFound, empties, tripsFocus, stops, hub }
  }, [tours, focusTourId])

  // ---- layer factory: called every frame (cheap; data refs are stable) ----
  renderRef.current = (sec) => {
    const overlay = overlayRef.current
    const d = dataRef.current
    if (!overlay || !d) return
    const pulse = reduced ? 1 : 0.5 + 0.5 * Math.sin(sec * 4)
    const pick = (info) => info.object && onSelect.current?.(info.object.tour_id)
    const tFocus = LOOP + (sec % LOOP)
    const road = { widthUnits: 'pixels', capRounded: true, jointRounded: true }
    overlay.setProps({
      layers: [
        new PathLayer({
          id: 'empties', data: d.empties, getPath: (x) => x.path, getColor: [...EMPTY_RGB, 235], getWidth: 3.5, ...road,
          getDashArray: [4, 4], dashJustified: true, extensions: [new PathStyleExtension({ dash: true })],
        }),
        new PathLayer({ id: 'roads-casing', data: [...d.roads, ...d.roadsFound], getPath: (x) => x.road, getColor: [255, 255, 255, 230], getWidth: 8, ...road }),
        new PathLayer({ id: 'roads', data: d.roads, getPath: (x) => x.road, getColor: (x) => x.color, getWidth: 4, ...road, pickable: true, onClick: pick }),
        new PathLayer({
          id: 'roads-found-glow', data: d.roadsFound, getPath: (x) => x.road, getColor: [...BLUE, 70], getWidth: 14, ...road,
          widthScale: 0.6 + pulse * 0.8, opacity: 0.25 + 0.75 * pulse,
        }),
        new PathLayer({
          id: 'roads-found', data: d.roadsFound, getPath: (x) => x.road, getColor: BLUE, getWidth: 4, ...road,
          getDashArray: [6, 4], dashJustified: true, extensions: [new PathStyleExtension({ dash: true })], pickable: true, onClick: pick,
        }),
        new ArcLayer({
          id: 'arcs', data: d.arcs, getSourcePosition: (x) => x.src, getTargetPosition: (x) => x.dst,
          getSourceColor: (x) => x.from, getTargetColor: (x) => x.to, getWidth: (x) => x.width, getHeight: 0.4,
          greatCircle: false, pickable: true, autoHighlight: true, highlightColor: [...INK, 200], onClick: pick,
          updateTriggers: { getWidth: d.focus?.tour_id ?? "all", getSourceColor: d.focus?.tour_id ?? "all", getTargetColor: d.focus?.tour_id ?? "all" },
        }),
        new TripsLayer({
          id: 'trips-glow', data: d.tripsFocus, getPath: (x) => x.path, getTimestamps: (x) => x.timestamps,
          getColor: (x) => x.colors.map((c) => [c[0], c[1], c[2], 60]), widthMinPixels: 16, capRounded: true, jointRounded: true,
          trailLength: LOOP * 0.15, currentTime: tFocus, fadeTrail: true,
        }),
        new TripsLayer({
          id: 'trips-focus', data: d.tripsFocus, getPath: (x) => x.path, getTimestamps: (x) => x.timestamps,
          getColor: (x) => x.colors, widthMinPixels: 6, capRounded: true, jointRounded: true,
          trailLength: LOOP * 0.15, currentTime: tFocus, fadeTrail: true,
        }),
        ...(d.hub ? hubLayers(d.hub, sec, pulse) : []),
        new ScatterplotLayer({
          id: 'stops', data: d.stops, getPosition: (x) => x.pos, radiusUnits: 'pixels', getRadius: 7,
          stroked: true, filled: true, getFillColor: [255, 255, 255], getLineColor: INK, lineWidthUnits: 'pixels', getLineWidth: 2.5,
        }),
        new TextLayer({
          id: 'labels', data: d.stops, getPosition: (x) => x.pos, getText: (x) => x.city, getSize: 12,
          getColor: INK, getPixelOffset: [0, -20], fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
          fontWeight: 600, background: true, getBackgroundColor: [255, 255, 255, 235], backgroundPadding: [6, 3],
          getBorderColor: [...INK, 40], getBorderWidth: 1, characterSet: 'auto',
        }),
      ],
    })
  }

  // ---- map: created once ----
  useEffect(() => {
    const map = new maplibregl.Map({
      container: el.current, style: STYLE, ...START,
      attributionControl: { compact: true }, maxPitch: 70, fadeDuration: 0,
    })
    mapRef.current = map
    // the map must re-measure itself whenever its container changes size (window resize, panels, devtools)
    const ro = new ResizeObserver(() => map.resize())
    ro.observe(el.current)
    map.on('error', (e) => { if (!e?.sourceId && !e?.tile) console.warn('[Map3D]', e?.error?.message || e) })

    map.on('load', () => {
      // Keep the base map quiet: drop every built-in label and road, keep land, water and borders.
      map.getStyle().layers.forEach((l) => {
        if (l.type === 'symbol' || /road|highway|bridge|tunnel|rail|aeroway|building/.test(l.id)) {
          map.setLayoutProperty(l.id, 'visibility', 'none')
        }
      })
      try {
        map.addSource('dem', { type: 'raster-dem', tiles: [DEM], encoding: 'terrarium', tileSize: 256, maxzoom: 14 })
        map.addSource('dem-hs', { type: 'raster-dem', tiles: [DEM], encoding: 'terrarium', tileSize: 256, maxzoom: 14 })
        const firstSymbol = map.getStyle().layers.find((l) => l.type === 'symbol')?.id
        map.addLayer({
          id: 'hillshade', type: 'hillshade', source: 'dem-hs',
          paint: {
            'hillshade-exaggeration': 0.3, 'hillshade-shadow-color': '#c9ced6',
            'hillshade-highlight-color': '#ffffff', 'hillshade-accent-color': '#e5e7eb',
          },
        }, firstSymbol)
        map.setTerrain({ source: 'dem', exaggeration: 1.6 })
        map.setSky?.({
          'sky-color': '#eef1f6', 'horizon-color': '#ffffff', 'fog-color': '#f8fafc',
          'sky-horizon-blend': 0.6, 'horizon-fog-blend': 0.7, 'fog-ground-blend': 0.85,
        })
      } catch (err) {
        console.warn('[Map3D] terrain disabled:', err?.message)
      }
      loaded.current = true
      flyRef.current()
    })

    const overlay = new MapboxOverlay({
      interleaved: false,
      getCursor: ({ isHovering, isDragging }) => (isDragging ? 'grabbing' : isHovering ? 'pointer' : 'grab'),
      getTooltip: ({ object, layer }) =>
        object && layer?.id?.startsWith('arcs') && { text: `${object.tourName}\n${legLabel(object)}`, className: 'map3d-tip' },
    })
    map.addControl(overlay)
    overlayRef.current = overlay

    // user interaction pauses the orbit
    const touch = (e) => { if (e.originalEvent) idleSince.current = performance.now() }
    for (const ev of ['dragstart', 'zoomstart', 'rotatestart', 'pitchstart', 'mousedown', 'touchstart', 'wheel']) map.on(ev, touch)

    let raf = 0
    let last = performance.now()
    const t0 = last
    const tick = (now) => {
      last = now
      renderRef.current(reduced ? 3 : (now - t0) / 1000)
      if (!reduced && dataRef.current?.focus && now - idleSince.current > IDLE_MS && !map.isMoving()) {
        // a slow sway around north instead of a full orbit
        map.setBearing(BEARING + SWAY_DEG * Math.sin(((now - t0) / 1000) * ORBIT_DEG_S * 0.1))
      }
      if (!reduced) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)

    return () => {
      ro.disconnect()
      cancelAnimationFrame(raf)
      try { map.removeControl(overlay) } catch { /* already gone */ }
      overlay.finalize()
      map.remove()
      mapRef.current = null
      overlayRef.current = null
      loaded.current = false
      flownTo.current = null
    }
  }, [reduced])

  // ---- camera swoop to the focused tour ----
  flyRef.current = () => {
    const map = mapRef.current
    const focus = dataRef.current?.focus
    if (!map || !loaded.current) return
    // no focus = overview: frame every loop at once
    const key = focus ? focus.tour_id : 'ALL'
    if (flownTo.current === key) return
    const b = new maplibregl.LngLatBounds()
    for (const t of focus ? [focus] : dataRef.current?.all ?? []) {
      for (const l of t.legs || []) { b.extend(ll(l.origin)); b.extend(ll(l.destination)) }
    }
    if (b.isEmpty()) return
    // Zoom: fit inside the area the floating UI leaves free. Centre: let the map's own
    // padding place the tour in that area (works under pitch, unlike a flat offset).
    const p = { ...NO_PAD, ...pad }
    // on small screens the floating panels would leave no map: shrink the padding to fit
    const { clientWidth: W, clientHeight: H } = map.getContainer()
    const kx = Math.min(1, (W * 0.55) / (p.left + p.right + 80 || 1))
    const ky = Math.min(1, (H * 0.55) / (p.top + p.bottom + 80 || 1))
    p.left *= kx; p.right *= kx; p.top *= ky; p.bottom *= ky
    const cur = map.getPadding()
    const fit = {}
    for (const k of ['top', 'right', 'bottom', 'left']) fit[k] = Math.max(0, p[k] + 40 - cur[k])
    const bearing = BEARING
    const cam = map.cameraForBounds(b, { padding: fit, bearing, maxZoom: 7.5 })
    if (!cam) return
    flownTo.current = key
    const duration = reduced ? 500 : 1600
    idleSince.current = performance.now() + duration
    map.flyTo({
      center: b.getCenter(), zoom: cam.zoom + 0.2, pitch: 50, bearing, padding: p,
      duration, curve: 1.3, essential: true,
    })
  }

  useEffect(() => {
    dataRef.current = data
    renderRef.current(3)
    flyRef.current()
  }, [data])

  return <div ref={el} className="map3d" />
}
