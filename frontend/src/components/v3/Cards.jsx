// Two tiny presentational pieces. Every role is turned into the same "item" shape:
// { id, kicker, title, big, bigNote, tag, tone, stats: [[label, value]], action, done, link }

export function CardRow({ items, selectedId, onSelect }) {
  if (!items) return null
  return (
    <div className="v3-cards">
      {items.map((it) => (
        <button
          key={it.id}
          className={`v3-card glass ${it.id === selectedId ? 'on' : ''}`}
          onClick={(e) => {
            onSelect(it.id)
            e.currentTarget.scrollIntoView({ behavior: 'smooth', inline: 'nearest', block: 'nearest' })
          }}
        >
          <span className="arrow">→</span>
          <span className="kicker">{it.kicker}</span>
          <span className="title">{it.title}</span>
          <span className="big">
            {it.big}
            <small>{it.bigNote}</small>
          </span>
          <span className={`tag ${it.tone ?? ''}`}>
            <i />
            {it.tag}
          </span>
        </button>
      ))}
    </div>
  )
}

export function FocusCard({ item, busy, onAction, onClose, onWhy }) {
  if (!item) return null
  return (
    <div className="v3-focus">
      <button className="close" onClick={onClose} aria-label="Close">✕</button>
      <div className="top glass">
        <span className="kicker">{item.kicker}</span>
        <span className="title">{item.title}</span>
        <span className="big">{item.big}</span>
        <span className="bignote">{item.bigNote}</span>
        {item.explain && <p className="explain">{item.explain}</p>}
        {item.list?.length > 0 && (<>
          {item.listTitle && <span className="list-title">{item.listTitle}</span>}
          <ul className="focus-list">
            {item.list.map((x) => (
              <li key={x.name}>
                <b>{x.name}</b>
                <span>{x.why}</span>
              </li>
            ))}
          </ul>
        </>)}
        {onWhy && (
          <button className="why-link" onClick={onWhy}>Why this? →</button>
        )}
      </div>
      <div className="bottom">
        {item.stats.map(([label, value]) => (
          <div key={label} className="row3">
            <span>{label}</span>
            <b>{value}</b>
          </div>
        ))}
        <button className={`go ${item.done ? 'done' : ''}`} disabled={busy || item.done || !onAction} onClick={onAction}>
          {item.done ? item.doneLabel : busy ? 'Working…' : item.action}
        </button>
        {item.link && (
          <a className="link" href={item.link} target="_blank" rel="noreferrer">Open in Meridian ↗</a>
        )}
      </div>
    </div>
  )
}
