import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

const GREETING = "Ask me where trucks drive home empty and what they could carry. I'll show every tool I use."
const SUGGESTION = 'Which trucks drive home empty from Dallas, and what could they carry?'

function ToolChip({ call }) {
  const [open, setOpen] = useState(false)
  const args = Object.values(call.args || {}).join(', ')
  return (
    <>
      <button className="chip" onClick={() => setOpen((o) => !o)}>
        {call.name}({args})
      </button>
      {open && <div className="chip-result">→ {call.result_preview}</div>}
    </>
  )
}

export default function AgentChat({ onError }) {
  const [messages, setMessages] = useState([{ role: 'agent', text: GREETING }])
  const [input, setInput] = useState('')
  const [thinking, setThinking] = useState(false)
  const logRef = useRef(null)

  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, thinking])

  async function send(text) {
    const message = text.trim()
    if (!message || thinking) return
    setMessages((m) => [...m, { role: 'user', text: message }])
    setInput('')
    setThinking(true)
    try {
      const res = await api.chat(message)
      setMessages((m) => [...m, { role: 'agent', text: res.reply, tools: res.tool_calls || [] }])
    } catch (e) {
      onError(e.message)
      setMessages((m) => [...m, { role: 'agent', text: `Sorry, that failed: ${e.message}` }])
    } finally {
      setThinking(false)
    }
  }

  const hasSent = messages.some((m) => m.role === 'user')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="chat-log" ref={logRef}>
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.text}
            {m.tools?.length > 0 && (
              <div className="chips">
                {m.tools.map((call, j) => <ToolChip key={j} call={call} />)}
              </div>
            )}
          </div>
        ))}
        {!hasSent && (
          <button className="suggest" onClick={() => send(SUGGESTION)}>{SUGGESTION}</button>
        )}
        {thinking && <div className="typing">Agent is thinking…</div>}
      </div>

      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault()
          send(input)
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask the agent…"
          disabled={thinking}
        />
        <button className="btn primary" type="submit" disabled={thinking || !input.trim()}>Send</button>
      </form>
    </div>
  )
}
