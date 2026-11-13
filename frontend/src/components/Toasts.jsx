export default function Toasts({ items }) {
  return (
    <div className="toasts">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.kind === 'info' ? '' : t.kind}`}>
          {t.text}
        </div>
      ))}
    </div>
  )
}
