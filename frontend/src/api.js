// Every request the UI makes lives here.
// VITE_USE_MOCK=true serves the JSON in ../mocks with a little in-memory state,
// so Fill it -> Approve -> green arc works before the backend is up.

import networkMock from '../mocks/network.json'
import cityDallasMock from '../mocks/city_dallas.json'
import pendingMock from '../mocks/pending_actions.json'
import chatMock from '../mocks/chat_reply.json'
import auditMock from '../mocks/audit.json'
import inboxMock from '../mocks/email_inbox.json'
import outboxMock from '../mocks/email_outbox.json'
import emailResultMock from '../mocks/email_process_result.json'
import toursMock from '../mocks/tours.json'
import tourActionsMock from '../mocks/tour_actions.json'
import carrierWeeksMock from '../mocks/carrier_weeks.json'
import shipperOffersMock from '../mocks/shipper_offers.json'
import priceSignalsMock from '../mocks/price_signals.json'
import returnLanesMock from '../mocks/return_lanes.json'
import backtestMock from '../mocks/network_backtest.json'
import reportsMock from '../mocks/reports.json'
import learnedMock from '../mocks/learned.json'

export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'
export const MERIDIAN_WEB_URL = import.meta.env.VITE_MERIDIAN_WEB_URL || ''

export function meridianLink(result) {
  if (!result) return null
  if (result.meridian_url) return result.meridian_url
  if (result.meridian_path && MERIDIAN_WEB_URL) return MERIDIAN_WEB_URL + result.meridian_path
  return null
}

// ---------- real API ----------

async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  })
  let data = null
  try {
    data = await res.json()
  } catch {
    // empty or non-JSON body
  }
  if (!res.ok) {
    const err = new Error(data?.detail || `${res.status} ${res.statusText} on ${path}`)
    err.status = res.status
    throw err
  }
  return data
}

const real = {
  getNetwork: () => request('/api/network'),
  getCity: (state, city) => request(`/api/city/${encodeURIComponent(state)}/${encodeURIComponent(city)}`),
  fill: (prospectId) => request('/api/fill', { method: 'POST', body: { prospect_id: prospectId } }),
  getActions: (status) => request(`/api/actions${status ? `?status=${status}` : ''}`),
  approve: (id) => request(`/api/actions/${id}/approve`, { method: 'POST' }),
  reject: (id, reason) => request(`/api/actions/${id}/reject`, { method: 'POST', body: { reason } }),
  chat: (message) => request('/api/agent/chat', { method: 'POST', body: { message } }),
  getAudit: () => request('/api/audit'),
  getInbox: () => request('/api/email/inbox'),
  getOutbox: () => request('/api/email/outbox'),
  simulateEmail: (file) => request('/api/email/simulate', { method: 'POST', body: { file } }),
  // tours: the broker's loops, the carrier's week, the manufacturer's offers
  getTours: () => request('/api/tours'),
  getCarrierWeeks: () => request('/api/carrier-weeks'),
  respondWeek: (tourId, decision, note) =>
    request(`/api/carrier-weeks/${tourId}/respond`, { method: 'POST', body: { decision, note } }),
  getOffers: () => request('/api/offers'),
  respondOffer: (offerId, decision) => request(`/api/offers/${offerId}/respond`, { method: 'POST', body: { decision } }),
  // prices carriers and shippers actually said on calls and in emails
  getPriceSignals: () => request('/api/price-signals'),
  // where trucks go home empty (real Meridian history) and the network-wide replay
  getReturnLanes: () => request('/api/return-lanes'),
  getBacktest: () => request('/api/network/backtest'),
  // weekly reports and what the brain learned from Meridian's history
  getReports: () => request('/api/reports/weekly'),
  getLearned: () => request('/api/learned'),
}

// ---------- mock API ----------

const clone = (x) => JSON.parse(JSON.stringify(x))
const wait = (ms = 350) => new Promise((r) => setTimeout(r, ms))

const db = {
  actions: [...clone(tourActionsMock.items), ...clone(pendingMock.items)],
  tours: clone(toursMock.items),
  weeks: clone(carrierWeeksMock.items),
  offers: clone(shipperOffersMock.items),
  audit: clone(auditMock.items),
  inbox: clone(inboxMock.items),
  outbox: clone(outboxMock.items),
  nextAction: 1007,
  nextQuote: 7300179,
  nextEmail: 4,
}

function log(actor, kind, text) {
  db.audit.unshift({ id: `E-${Date.now()}`, at: new Date().toISOString(), actor, kind, text })
}

function findProspect(id) {
  return cityDallasMock.prospects.find((p) => p.prospect_id === id)
}

function mockCity(state, city) {
  if (city === 'Dallas' && state === 'TX') return clone(cityDallasMock)
  const c = networkMock.cities.find((x) => x.city === city && x.state === state)
  if (!c) throw new Error(`No city ${city}, ${state} in the network.`)
  return {
    city: c.city,
    state: c.state,
    inbound: c.inbound,
    outbound: c.outbound,
    summary: c.one_way
      ? `${c.inbound} loads in, 0 out. Mock data only has prospects for Dallas.`
      : `${c.inbound} in, ${c.outbound} out. Not a one-way city.`,
    prospects: [],
  }
}

const mock = {
  async getNetwork() {
    await wait(500)
    return clone(networkMock)
  },
  async getCity(state, city) {
    await wait()
    return mockCity(state, city)
  },
  async fill(prospectId) {
    await wait()
    const p = findProspect(prospectId)
    if (!p) throw new Error(`Unknown prospect ${prospectId}.`)
    if (!p.ok) throw new Error(p.reasons.find((r) => !r.passed)?.text || 'This prospect is blocked.')
    if (db.actions.some((a) => a.prospect_id === prospectId && a.status === 'pending')) {
      throw new Error('This prospect is already waiting for approval.')
    }
    const id = `A-${db.nextAction++}`
    const { origin, destination } = p.lane
    db.actions.unshift({
      action_id: id,
      type: 'create_quote',
      status: 'pending',
      tier: 'write',
      title: `Create return quote: ${p.customer}`,
      summary: `TL ${p.equipment === 'R' ? 'reefer' : 'dry van'} ${origin.city}, ${origin.state} -> ${destination.city}, ${destination.state}, sell $${p.est_sell.toLocaleString()} at ${p.gp_pct}% GP`,
      confidence: Math.min(0.97, p.score / 100),
      prospect_id: prospectId,
      miles: p.miles,
      reasoning: p.reasons.map((r) => `${r.passed ? '✓' : '✗'} ${r.text}`).join('\n'),
      payload: { customer_id: p.customer_id, facility_id: p.facility_id, mode: 'TL', equipment_type: p.equipment },
      created_at: new Date().toISOString(),
      created_by: 'agent',
    })
    log('agent', 'propose', `Proposed ${id}: return quote for ${p.customer}`)
    return { action_id: id, status: 'pending', title: `Create return quote: ${p.customer}`, message: 'Queued for approval' }
  },
  async getActions(status) {
    await wait(150)
    return { items: clone(status ? db.actions.filter((a) => a.status === status) : db.actions) }
  },
  async approve(id) {
    await wait(700)
    const a = db.actions.find((x) => x.action_id === id)
    if (!a) throw new Error(`Unknown action ${id}.`)
    if (a.status !== 'pending') throw new Error(`Action ${id} is already ${a.status}.`)
    a.status = 'done'
    const p = a.prospect_id ? findProspect(a.prospect_id) : null
    if (a.type === 'book_tour') {
      a.result = bookTour(a.tour_id)
    } else if (a.type === 'create_quote') {
      const quoteId = String(db.nextQuote++)
      a.result = {
        summary: `Quote ${quoteId} created${p ? ` for ${p.customer}` : ''}`,
        quote_id: quoteId,
        sell_total: p?.est_sell ?? null,
        gp_pct: p?.gp_pct ?? null,
        miles: a.miles ?? p?.miles ?? 0,
        meridian_path: `/quotes/${quoteId}`,
        lane: p ? p.lane : laneFromPayload(a.payload),
      }
    } else {
      a.result = { summary: `${a.title}: done`, miles: 0 }
    }
    log('ali', 'approve', `Approved ${id}: ${a.result.summary}`)
    return clone(a)
  },
  async reject(id, reason) {
    await wait()
    const a = db.actions.find((x) => x.action_id === id)
    if (!a) throw new Error(`Unknown action ${id}.`)
    a.status = 'rejected'
    a.reject_reason = reason
    log('ali', 'reject', `Rejected ${id}: ${reason}`)
    return clone(a)
  },
  async chat(message) {
    await wait(1100)
    log('agent', 'chat', `Answered: "${message.slice(0, 60)}"`)
    return clone(chatMock)
  },
  async getAudit() {
    await wait(150)
    return { items: clone(db.audit) }
  },
  async getInbox() {
    await wait(150)
    return { items: clone(db.inbox) }
  },
  async getOutbox() {
    await wait(150)
    return { items: clone(db.outbox) }
  },
  async getEmailSamples() {
    return { items: ['email_01.json', 'email_02.json', 'email_03.json', 'email_04.json', 'email_05.json', 'email_06.json'] }
  },
  async simulateEmail(file) {
    await wait(900)
    const result = clone(emailResultMock)
    const n = db.nextEmail++
    result.email.id = `M-${String(n).padStart(2, '0')}`
    result.email.subject = `${result.email.subject} (${file})`
    result.email.received_at = new Date().toISOString()
    result.actions_created.forEach((a, i) => {
      a.action_id = `A-${db.nextAction++}`
      a.created_at = result.email.received_at
      result.email.action_ids[i] = a.action_id
      db.actions.unshift(a)
    })
    db.inbox.unshift(result.email)
    log('agent', 'email', `Classified ${result.email.id} as ${result.email.kind} (${result.email.confidence})`)
    return result
  },
}

// Approving a book_tour action: quote the missing legs, cover the open ones, offer the week to the carrier.
function bookTour(tourId) {
  const t = db.tours.find((x) => x.tour_id === tourId)
  if (!t) throw new Error(`Unknown tour ${tourId}.`)
  const quotes = []
  const lanes = []
  t.legs.forEach((l) => {
    if (l.status === 'missing') {
      l.status = 'quoted'
      l.quote_id = String(db.nextQuote++)
      quotes.push(l.quote_id)
      lanes.push({ origin: l.origin, destination: l.destination })
    } else if (l.status === 'needs_carrier') {
      l.status = 'covered'
    }
  })
  t.status = 'booked'
  const week = db.weeks.find((w) => w.tour_id === tourId)
  if (week) week.legs.forEach((l) => { if (l.status === 'missing') l.status = 'quoted'; if (l.status === 'needs_carrier') l.status = 'covered' })
  return {
    summary: `Tour ${tourId} booked: ${quotes.length} new ${quotes.length === 1 ? 'quote' : 'quotes'}, week offered to ${t.carrier.name}`,
    tour_id: tourId,
    quote_ids: quotes,
    sell_total: t.totals.sell,
    gp_pct: t.totals.tour_gp_pct,
    profit_unlocked: t.totals.profit_unlocked,
    miles: t.totals.standalone_empty_miles - t.totals.empty_miles,
    lanes,
    meridian_path: quotes.length ? `/quotes/${quotes[0]}` : null,
  }
}

Object.assign(mock, {
  async getReturnLanes() {
    await wait(250)
    return clone(returnLanesMock)
  },
  async getReports() {
    await wait(250)
    return clone(reportsMock)
  },
  async getLearned() {
    await wait(200)
    return clone(learnedMock)
  },
  async getBacktest() {
    await wait(150)
    return clone(backtestMock)
  },
  async getPriceSignals() {
    await wait(300)
    return clone(priceSignalsMock)
  },
  async getTours() {
    await wait(300)
    return { items: clone(db.tours) }
  },
  async getCarrierWeeks() {
    await wait(250)
    return { items: clone(db.weeks) }
  },
  async respondWeek(tourId, decision, note) {
    await wait(500)
    const w = db.weeks.find((x) => x.tour_id === tourId)
    if (!w) throw new Error(`No week offer for tour ${tourId}.`)
    if (w.status !== 'offered') throw new Error(`This week was already ${w.status}.`)
    w.status = decision === 'accept' ? 'accepted' : 'countered'
    w.note = note || null
    const t = db.tours.find((x) => x.tour_id === tourId)
    if (t) t.carrier_status = w.status
    log(w.carrier.vendor_id.toLowerCase(), 'carrier', `${w.carrier.name} ${w.status} the week for ${tourId}${note ? `: "${note}"` : ''}`)
    return clone(w)
  },
  async getOffers() {
    await wait(250)
    return { items: clone(db.offers) }
  },
  async respondOffer(offerId, decision) {
    await wait(500)
    const o = db.offers.find((x) => x.offer_id === offerId)
    if (!o) throw new Error(`Unknown offer ${offerId}.`)
    if (o.status !== 'open') throw new Error(`This offer is already ${o.status}.`)
    o.status = decision === 'accept' ? 'accepted' : 'declined'
    log('shipper', 'offer', `${o.shipper.name} ${o.status} ${offerId}: ${o.title}`)
    return clone(o)
  },
})

const CITY_COORDS = {
  'Aurora, CO': { city: 'Aurora', state: 'CO', lat: 39.73, lng: -104.83 },
  'Des Moines, IA': { city: 'Des Moines', state: 'IA', lat: 41.59, lng: -93.62 },
  'Fort Worth, TX': { city: 'Fort Worth', state: 'TX', lat: 32.75, lng: -97.33 },
  'Columbus, OH': { city: 'Columbus', state: 'OH', lat: 39.96, lng: -83.0 },
}

function laneFromPayload(payload = {}) {
  const origin = CITY_COORDS[payload.origin]
  const destination = CITY_COORDS[payload.destination]
  return origin && destination ? { origin, destination } : null
}

// Routes the backend doesn't serve yet (tours, empty trips, reports, learning) fall back to the
// real-data files in ../mocks, so the live API can be switched on before every route exists.
const NOT_IN_BACKEND_YET = [
  'getTours', 'getCarrierWeeks', 'respondWeek', 'getOffers', 'respondOffer',
  'getPriceSignals', 'getReturnLanes', 'getBacktest', 'getReports', 'getLearned',
]
const missing = new Set() // routes that returned 404 once: stop asking the backend for them
for (const name of NOT_IN_BACKEND_YET) {
  const live = real[name]
  real[name] = async (...args) => {
    if (missing.has(name)) return mock[name](...args)
    try {
      return await live(...args)
    } catch (e) {
      if (e.status === 404) {
        missing.add(name)
        return mock[name](...args)
      }
      throw e
    }
  }
}
// Asher's email routes (contracts/email_*.json) use their own field names: translate them here.
const nameOf = (addr = '') => {
  const m = String(addr).match(/^\s*"?([^"<]+?)"?\s*<[^>]+>/)
  if (m) return m[1].trim()
  const domain = String(addr).split('@')[1] || addr
  return domain.split('.')[0].replace(/[-_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}
const toInboxRow = (e) => ({
  id: e.email_id,
  from: e.from_addr,
  from_name: nameOf(e.from_addr),
  subject: e.subject,
  received_at: e.received_at,
  kind: String(e.kind || 'other').toLowerCase(),
  confidence: e.confidence ?? 0,
  status: e.status,
  body: e.body,
  extracted: e.extracted || {},
  matched: e.matched,
  action_ids: e.action_ids || [],
})
real.getInbox = async () => {
  try {
    const list = await request('/api/email/inbox')
    // the list has no body or extracted fields; the detail route does (only a handful of emails)
    const details = await Promise.all(list.items.map((e) => request(`/api/email/${e.email_id}`).catch(() => e)))
    return { items: details.map(toInboxRow) }
  } catch (e) {
    if (e.status === 404) return { items: [], not_connected: true }
    throw e
  }
}
real.getOutbox = async () => {
  try {
    const out = await request('/api/email/outbox')
    return {
      items: out.items.map((r) => ({ id: r.reply_id, in_reply_to: r.email_id, to: r.to_addr, subject: r.subject, body: r.body, status: r.status, action_id: r.action_id })),
    }
  } catch (e) {
    if (e.status === 404) return { items: [] }
    throw e
  }
}
real.getEmailSamples = () => request('/api/email/samples')
real.simulateEmail = async (file) => {
  const r = await request('/api/email/simulate', { method: 'POST', body: { file } })
  const detail = await request(`/api/email/${r.email_id}`).catch(() => r)
  return { email: toInboxRow({ ...detail, ...r }), actions_created: r.actions_created || [] }
}
// book_tour actions live in the mock queue until the backend has them
const liveApprove = real.approve
real.approve = (id) => (String(id).startsWith('A-L') ? mock.approve(id) : liveApprove(id))

export const api = USE_MOCK ? mock : real
