import React from 'react'

// A spectrum of stances toward missing evidence, ordered from most to least
// benefit of the doubt. They were previously Avoid / Neutral / Show gaps --
// but "show gaps" is a display action, not a routing policy, and it did
// nothing at all: the router treated it identically to Neutral.
const OPTIONS = [
  ['neutral', 'Neutral', 'Costs distance only. We make no assumption about a street we have not observed.'],
  ['assume_typical', 'Assume typical', 'Scored as darkly as the average street we have observed — a stated prior rather than a silent guess.'],
  ['avoid', 'Avoid unknown', 'Heavily penalised. Routed through only when there is no observed alternative.'],
]

export function UnknownPolicy({ policy, onChange }) {
  const active = OPTIONS.find(([value]) => value === policy) || OPTIONS[0]

  return <section className="unknown-control">
    <p className="eyebrow">UNOBSERVED STREETS</p>
    <div className="policy-options" role="radiogroup" aria-label="Policy for streets with no lighting evidence">
      {OPTIONS.map(([value, label, description]) => (
        <button
          key={value}
          title={description}
          onClick={() => onChange(value)}
          className={policy === value ? 'active' : ''}
          role="radio"
          aria-checked={policy === value}
        >
          {label}
        </button>
      ))}
    </div>
    <p>{active[2]}</p>
  </section>
}