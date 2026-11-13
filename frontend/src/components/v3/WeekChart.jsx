import { useState } from 'react'

// One measure over weeks: thin bars (or a line for percentages), a recessive baseline,
// a label on the latest value only, and a hover tooltip on every week.
export default function WeekChart({ title, data, value, format, kind = 'bar', color = '#111827', highlightLast = true }) {
  const [hover, setHover] = useState(null)
  const W = 560
  const H = 150
  const pad = { l: 8, r: 8, t: 22, b: 22 }
  const vals = data.map((d) => value(d) ?? null)
  const max = Math.max(1, ...vals.filter((v) => v != null))
  const min = kind === 'line' ? Math.min(...vals.filter((v) => v != null), max) * 0.95 : 0
  const step = (W - pad.l - pad.r) / data.length
  const y = (v) => pad.t + (H - pad.t - pad.b) * (1 - (v - min) / (max - min || 1))
  const x = (i) => pad.l + step * i + step / 2
  const lastIdx = vals.length - 1
  const pts = vals.map((v, i) => (v == null ? null : [x(i), y(v)])).filter(Boolean)

  return (
    <figure className="wk">
      <figcaption>{title}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title} onMouseLeave={() => setHover(null)}>
        <line x1={pad.l} x2={W - pad.r} y1={H - pad.b} y2={H - pad.b} className="wk-base" />
        {kind === 'bar' &&
          vals.map((v, i) =>
            v == null ? null : (
              <rect
                key={i}
                x={x(i) - Math.max(2, step * 0.32)}
                width={Math.max(4, step * 0.64)}
                y={y(Math.max(v, 0))}
                height={Math.max(1, H - pad.b - y(Math.max(v, 0)))}
                rx="3"
                fill={color}
                opacity={hover == null ? (highlightLast && i !== lastIdx ? 0.35 : 1) : hover === i ? 1 : 0.25}
              />
            ),
          )}
        {kind === 'line' && (
          <>
            <polyline points={pts.map((p) => p.join(',')).join(' ')} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
            {pts.map(([px, py], i) => (
              <circle key={i} cx={px} cy={py} r={hover === i || i === pts.length - 1 ? 4.5 : 0} fill={color} stroke="#fff" strokeWidth="2" />
            ))}
          </>
        )}
        {vals[lastIdx] != null && (
          <text x={x(lastIdx)} y={y(vals[lastIdx]) - 7} textAnchor="end" className="wk-last">
            {format(vals[lastIdx])}
          </text>
        )}
        {/* hit targets wider than the marks */}
        {data.map((d, i) => (
          <rect key={`h${i}`} x={pad.l + step * i} width={step} y={0} height={H} fill="transparent" onMouseEnter={() => setHover(i)} />
        ))}
        <text x={pad.l} y={H - 6} className="wk-axis">{data[0]?.week?.slice(5)}</text>
        <text x={W - pad.r} y={H - 6} textAnchor="end" className="wk-axis">{data[lastIdx]?.week?.slice(5)}</text>
      </svg>
      {hover != null && (
        <div className="wk-tip" style={{ left: `${(x(hover) / W) * 100}%` }}>
          <b>Week of {data[hover].week.slice(5)}</b>
          <span>{vals[hover] == null ? 'no data' : format(vals[hover])}</span>
        </div>
      )}
    </figure>
  )
}
