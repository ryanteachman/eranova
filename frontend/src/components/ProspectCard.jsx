const EQUIPMENT = {
  V: 'Dry van',
  R: 'Reefer',
  F: 'Flatbed',
  SV: 'Sprinter',
  SB: 'Box truck',
  HS: 'Hotshot',
}

const money = (n) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

function humanize(category = '') {
  const text = category.replace(/_/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

const place = (p) => `${p.city}, ${p.state}`

export default function ProspectCard({ prospect, queued, busy, onFill }) {
  const p = prospect
  const blocked = !p.ok
  const firstFail = p.reasons.find((r) => !r.passed)
  const days = p.transit_days === 1 ? 'day' : 'days'

  return (
    <div className={`card prospect ${blocked ? 'blocked' : ''}`}>
      <div className="score" style={{ '--pct': blocked ? 0 : p.score }}>
        <span>{blocked ? '—' : p.score}</span>
      </div>

      <div className="stack" style={{ gap: 8 }}>
        <div className="row between">
          <h3 className="h3">{p.customer}</h3>
          {!blocked &&
            (queued ? (
              <button className="btn small" disabled>Queued ✓</button>
            ) : (
              <button className="btn primary small" disabled={busy} onClick={onFill}>
                {busy ? 'Queuing…' : 'Fill it'}
              </button>
            ))}
        </div>

        <div className="lane">
          {place(p.lane.origin)} → {place(p.lane.destination)} · {Math.round(p.miles)} mi · ~
          {p.transit_days} {days}
        </div>

        <div className="row wrap">
          <span className={`badge eq-${p.equipment}`}>{EQUIPMENT[p.equipment] || p.equipment}</span>
          <span className="badge">{humanize(p.category)}</span>
          <span className="muted small">{p.commodity}</span>
        </div>

        <div className="money-row">
          <b>{money(p.est_sell)}</b>
          <span>{p.gp_pct}% GP</span>
          <span className="muted">buy {money(p.est_buy)}</span>
        </div>

        <ul className="reasons">
          {p.reasons.map((r) => (
            <li key={r.check} className={r.passed ? '' : 'failed'}>
              <span className={r.passed ? 'pass' : 'fail'}>{r.passed ? '✓' : '✗'}</span>
              {r.text}
            </li>
          ))}
        </ul>

        {blocked && firstFail && <div className="blocked-line">Blocked: {firstFail.text}</div>}
      </div>
    </div>
  )
}
