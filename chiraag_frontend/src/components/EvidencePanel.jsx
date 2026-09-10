import React, { useState, useEffect } from 'react'
import { postAudit } from '../lib/api'

const Bar = ({ label, value }) => (
  <div className="score-row">
    <span>{label}</span>
    <div className="bar">
      <i style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  </div>
)

const STATE_LABEL = {
  audited: 'Confirmed by a night audit',
  predicted: 'Inferred from street imagery',
  // Cameras have been down this street and found no lamp. That is a positive
  // observation of darkness, not a gap in the data, and it must not read as
  // one in the drawer.
  imaged_dark: 'Imagery available, no streetlights detected',
  unobserved: 'No imagery available',
}

const RATINGS = [
  [1, 'Pitch dark'],
  [2, 'Mostly dark'],
  [3, 'Patchy'],
  [4, 'Mostly lit'],
  [5, 'Well lit'],
]

export function EvidencePanel({ evidence, onClose, onAudited }) {
  const [rating, setRating] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [auditError, setAuditError] = useState(null)
  const [showForm, setShowForm] = useState(false)

  // Reset the form whenever a different street is selected.
  useEffect(() => {
    setRating(null)
    setSubmitting(false)
    setAuditError(null)
    setShowForm(false)
  }, [evidence?.road_id])

  if (!evidence) return null

  // The API returns NULL for anything we have no evidence on. Treat missing
  // evidence as missing -- never as zero darkness.
  const unknown =
    evidence.observation_state === 'unobserved' ||
    evidence.dark_fraction === null ||
    evidence.dark_fraction === undefined

  const length = Math.round(evidence.length_m ?? 0)
  const darkFraction = evidence.dark_fraction ?? 0
  const litPercent = Math.round((1 - darkFraction) * 100)
  const darkMetres = Math.round(darkFraction * (evidence.length_m ?? 0))

  // NULL after an audit -- a rating says how dark a street feels overall,
  // not where the gaps fall.
  const hasGap =
    evidence.longest_gap_m !== null && evidence.longest_gap_m !== undefined
  const longestGap = Math.round(evidence.longest_gap_m ?? 0)

  const audited = evidence.observation_state === 'audited'
  const imagedDark = evidence.observation_state === 'imaged_dark'

  async function submitAudit() {
    if (rating === null) return

    try {
      setSubmitting(true)
      setAuditError(null)

      await postAudit(evidence.road_id, rating)

      await onAudited?.(evidence.road_id)
    } catch (error) {
      console.error(error)
      setAuditError(error.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <aside className="evidence-drawer" aria-label="Segment evidence">
      <div className="drawer-heading">
        <div>
          <p className="eyebrow">EVIDENCE</p>
          <h2>SEGMENT {evidence.road_id}</h2>
        </div>

        <button
          onClick={onClose}
          className="close"
          aria-label="Close evidence"
        >
          x
        </button>
      </div>

      <p className="segment-state">
        {STATE_LABEL[evidence.observation_state] || evidence.observation_state}
        {' · '}
        {length} m long
      </p>

      {unknown ? (
        <>
          <p className="unknown-message">
            We do not have enough street imagery to say anything about the
            lighting here. That is not the same as saying it is dark, and
            CHIRAAG will not score it as dark.
          </p>

          <div className="score-explanation">
            <p className="eyebrow">WHAT WOULD CHANGE THIS</p>

            <p className="plain-reason">
              A Mapillary capture along this street, or a night audit from
              someone who has walked it.
            </p>
          </div>
        </>
      ) : (
        <>
          <div className="evidence-stats">
            <div>
              <b>{litPercent}%</b>
              <span>OF THIS STREET IS LIT</span>
            </div>

            {hasGap && (
              <div>
                <b>{longestGap} m</b>
                <span>LONGEST DARK GAP</span>
              </div>
            )}
          </div>

          <div className="score-explanation">
            <p className="eyebrow">
              {darkFraction > 0
                ? 'WHY CHIRAAG FLAGS THIS'
                : 'WHY THIS IS PREFERRED'}
            </p>

            <p className="plain-reason">
              {audited
                ? `Someone who walked this street rated it ${litPercent}% lit. Ground-truth ratings override our imagery estimate.`
                : imagedDark
                  ? `Street-level imagery covers this ${length} m stretch and no street light was detected anywhere along it, so CHIRAAG treats it as unlit. That is weaker evidence than a lamp we can see, so it is scored cautiously -- a night audit would settle it.`
                  : darkFraction > 0
                    ? `About ${darkMetres} m of this ${length} m stretch falls outside the reach of any detected street light${
                        hasGap ? `, the longest unbroken dark run being ${longestGap} m` : ''
                      }.`
                    : `Detected street lights cover this entire ${length} m stretch, so routing over it adds no unlit exposure.`}
            </p>

            <Bar label="Lighting coverage" value={litPercent} />

            <div className="data-line">
              <span>Unlit distance</span>
              <b>{darkMetres} m</b>
            </div>

            {hasGap && (
              <div className="data-line">
                <span>Longest dark gap</span>
                <b>{longestGap} m</b>
              </div>
            )}
          </div>
        </>
      )}

      <div className="audit-block">
        {showForm ? (
          <>
            <p className="eyebrow">HOW LIT IS THIS STREET AT NIGHT?</p>

            <div className="audit-options" role="radiogroup" aria-label="Lighting rating">
              {RATINGS.map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={rating === value}
                  className={rating === value ? 'active' : ''}
                  onClick={() => setRating(value)}
                >
                  {label}
                </button>
              ))}
            </div>

            {auditError && <p className="audit-error">{auditError}</p>}

            <button
              type="button"
              className="audit-submit"
              disabled={rating === null || submitting}
              onClick={submitAudit}
            >
              {submitting ? 'Recording...' : 'Submit audit'}
            </button>

            <p className="audit-note">
              Your rating replaces our imagery estimate for this street and
              takes effect on the next route.
            </p>
          </>
        ) : (
          <button
            type="button"
            className="audit-open"
            onClick={() => setShowForm(true)}
          >
            I have walked this street — rate the lighting
          </button>
        )}
      </div>

      <div className="evidence-source">
        {audited
          ? 'Night audit · ground truth'
          : unknown
            ? 'No Mapillary street-light detections on this segment'
            : 'Mapillary street-light detections · 25 m assumed light reach'}
      </div>
    </aside>
  )
}