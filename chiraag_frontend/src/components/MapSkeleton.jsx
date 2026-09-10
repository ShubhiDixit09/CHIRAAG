import React, { useEffect, useState } from 'react'

// Free hosting suspends the API after a quiet spell, and the first request
// afterwards waits on a cold start -- routinely a minute. A bare spinner for
// that long reads as broken, so the message escalates instead: name the wait,
// explain it, then keep a counter running so it stays visibly alive rather
// than apparently hung. The explanation matters more than the animation --
// people wait happily when they know why.
const STAGES = [
  {
    after: 0,
    title: 'Finding your route',
    detail: 'Scoring the streets along the way.',
  },
  {
    after: 7,
    title: 'Waking the server',
    detail: 'Our demo server sleeps when nobody is using it. The first request takes about a minute.',
  },
  {
    after: 30,
    title: 'Still waking up',
    detail: 'Nearly there. This only happens on the first request.',
  },
]

export function MapSkeleton() {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const started = Date.now()

    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - started) / 1000))
    }, 1000)

    return () => clearInterval(id)
  }, [])

  // Last stage whose threshold has passed.
  const stage =
    [...STAGES].reverse().find(s => elapsed >= s.after) || STAGES[0]

  return (
    <div className="map-skeleton" role="status" aria-live="polite">
      <div className="wake-notice">
        <i className="wake-spinner" aria-hidden="true" />

        <b>{stage.title}</b>
        <span>{stage.detail}</span>

        {elapsed >= 7 && <small>{elapsed}s</small>}
      </div>
    </div>
  )
}
