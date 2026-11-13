import { useCallback, useEffect, useRef, useState } from 'react'

// Calls fn now and then every `ms` milliseconds. Keeps the last good data while refreshing,
// so panels don't flash back to a skeleton on every poll.
export default function usePoll(fn, ms, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const fnRef = useRef(fn)
  fnRef.current = fn

  const refresh = useCallback(async () => {
    try {
      setData(await fnRef.current())
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    refresh()
    if (!ms) return undefined
    const id = setInterval(refresh, ms)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ms, refresh, ...deps])

  return { data, error, loading: data === null && !error, refresh }
}
