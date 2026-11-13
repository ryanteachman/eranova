import { MERIDIAN_WEB_URL } from '../api.js'

export default function MeridianFrame() {
  if (!MERIDIAN_WEB_URL) {
    return (
      <div className="empty">
        No Meridian URL set. Add <code>VITE_MERIDIAN_WEB_URL=...</code> to <code>frontend/.env.local</code> and
        restart the dev server.
      </div>
    )
  }

  return (
    <div className="frame-wrap">
      <div className="frame-bar">
        <b>Meridian TMS (live)</b>
        <span className="muted small">If this stays blank, the site blocks embedding.</span>
        <a className="btn small" href={MERIDIAN_WEB_URL} target="_blank" rel="noreferrer" style={{ marginLeft: 'auto' }}>
          Open in new window ↗
        </a>
      </div>
      <iframe src={MERIDIAN_WEB_URL} title="Meridian TMS" />
    </div>
  )
}
