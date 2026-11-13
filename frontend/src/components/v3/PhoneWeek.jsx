import { useState } from 'react'
import { api } from '../../api.js'
import './PhoneWeek.css'

// The driver's phone in the same quiet style as the rest of v3:
// one big number, one tag, the route, one blue action.

const usd0 = (n) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const day = (d) => new Date(`${d}T12:00:00`).toLocaleDateString('en-US', { weekday: 'short', month: 'numeric', day: 'numeric' })
const EQ = { V: 'Dry van', R: 'Reefer', F: 'Flatbed', SV: 'Sprinter' }

function Route({ legs }) {
  return (
    <ol className="pw-route">
      {legs.map((l, i) =>
        l.kind === 'empty' ? (
          <li key={l.seq} className="pw-empty">
            {l.miles} mi empty
          </li>
        ) : (
          <li key={l.seq} className="pw-leg">
            <span className={`pw-dot ${l.status === 'missing' ? 'found' : ''}`} />
            <div>
              <b>
                {l.origin.city} → {l.destination.city}
              </b>
              <span>
                {day(l.pickup)} · {l.miles} mi · {l.commodity}
              </span>
            </div>
            <em>{usd0(l.pay)}</em>
          </li>
        ),
      )}
      <li className="pw-home">Home in {legs.length ? legs[legs.length - 1].destination.city : ''}</li>
    </ol>
  )
}

export default function PhoneWeek({ week, onResponded, onToast }) {
  const [busy, setBusy] = useState(false)
  const [countering, setCountering] = useState(false)
  const [note, setNote] = useState('')
  if (!week) return null

  const t = week.totals
  const first = (week.carrier.driver || week.carrier.name).split(' ')[0]

  async function respond(decision) {
    setBusy(true)
    try {
      const updated = await api.respondWeek(week.tour_id, decision, decision === 'counter' ? note : undefined)
      onToast(decision === 'accept' ? `Week accepted. ${first} is home ${day(t.home_by)}.` : 'Counter sent to the broker', 'success')
      setCountering(false)
      onResponded(updated)
    } catch (e) {
      onToast(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="pw-phone">
      <div className="pw-island" />
      <div className="pw-screen">
        <div className="pw-status">
          <span>9:41</span>
          <span>●●● ▮</span>
        </div>

        <div className="pw-top">
          <span className="pw-kicker">
            {week.carrier.truck} · {EQ[week.carrier.equipment] ?? week.carrier.equipment}
          </span>
          <span className="pw-hi">Hi {first}, your week is full</span>
          <span className="pw-big">{usd0(t.pay)}</span>
          <span className="pw-note">instead of {usd0(week.standalone.pay)} and a drive home empty</span>
          <span className="pw-tag">
            <i /> Home {day(t.home_by)}
          </span>
        </div>

        <div className="pw-stats">
          <div>
            <b>{t.loaded_pct}%</b>
            <span>loaded</span>
          </div>
          <div>
            <b>${t.per_mile}</b>
            <span>per mile</span>
          </div>
          <div>
            <b>{t.idle_days}</b>
            <span>idle days</span>
          </div>
        </div>

        <div className="pw-scroll">
          <Route legs={week.legs} />
        </div>

        <div className="pw-bottom">
          {week.status === 'offered' ? (
            countering ? (
              <>
                <input
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="e.g. $150 more on the Texas leg"
                  autoFocus
                />
                <div className="pw-row">
                  <button className="pw-link" onClick={() => setCountering(false)} disabled={busy}>Cancel</button>
                  <button className="pw-go small" onClick={() => respond('counter')} disabled={busy || !note.trim()}>
                    {busy ? 'Sending…' : 'Send counter'}
                  </button>
                </div>
              </>
            ) : (
              <>
                <button className="pw-go" onClick={() => respond('accept')} disabled={busy}>
                  {busy ? 'Accepting…' : 'Accept the week'}
                </button>
                <button className="pw-link" onClick={() => setCountering(true)} disabled={busy}>Counter</button>
              </>
            )
          ) : (
            <span className="pw-done">{week.status === 'accepted' ? '✓ Accepted. Dispatch has your week.' : 'Counter sent'}</span>
          )}
        </div>
      </div>
    </div>
  )
}
