import React, { useEffect, useState, useRef } from 'react'
import { getRoute, getSegment, USE_MOCK_DATA } from './lib/api'
import { Header } from './components/Header'
import { RouteComparison } from './components/RouteComparison'
import { HeroMetric } from './components/HeroMetric'
import { TimeControl } from './components/TimeControl'
import { DetourControl } from './components/DetourControl'
import { UnknownPolicy as UnknownPolicyControl } from './components/UnknownPolicy'
import { EvidencePanel } from './components/EvidencePanel'
import { MapView } from './components/MapView'
import { MapSkeleton } from './components/MapSkeleton'
import { useSheetDrag } from './lib/useSheetDrag'


// Known-good pairs inside the surveyed network, with coordinates baked in so
// they never depend on a geocoding round-trip.
//
// These were selected by evaluating all 92 landmark pairs in the survey area
// against the live scores: each one below produces a genuinely different and
// measurably safer route, with enough evidence coverage to stand up to "how
// much of this do you actually know?".
//
// The previous set was chosen before the network was rescored. Two of its
// three journeys had since become identical to the shortest path -- India
// Gate to Connaught Place returned 0 m avoided at 98% coverage, meaning the
// shortest route there is genuinely already the best one. Good result,
// terrible demo. Re-measure this list whenever the scores change.
//
//   India Gate -> Mandi House       451 m avoided,  +28 m,  74% observed
//   Secretariat -> Gole Market      327 m avoided, +146 m,  60% observed
//   Janpath -> Bangla Sahib         245 m avoided,  +68 m,  59% observed
const PRESETS = [
  {
    label: 'India Gate \u2192 Mandi House',
    from: 'India Gate',
    fromCoords: { lat: 28.612945, lon: 77.229466 },
    to: 'Mandi House',
    toCoords: { lat: 28.6258, lon: 77.2344 },
  },
  {
    label: 'Secretariat \u2192 Gole Market',
    from: 'Central Secretariat',
    fromCoords: { lat: 28.6152, lon: 77.2122 },
    to: 'Gole Market',
    toCoords: { lat: 28.6335, lon: 77.2065 },
  },
  {
    label: 'Janpath \u2192 Bangla Sahib',
    from: 'Janpath',
    fromCoords: { lat: 28.6242, lon: 77.2185 },
    to: 'Bangla Sahib',
    toCoords: { lat: 28.6262, lon: 77.2090 },
  },
]

const DEFAULT_JOURNEY = PRESETS[0]

// A range input emits a value for every pixel of the drag. Without a delay,
// sliding the hour control from midday to midnight fires a dozen route
// requests, each one rebuilding the street graph server-side. Long enough to
// swallow a drag, short enough that a single click still feels immediate.
const ROUTE_DEBOUNCE_MS = 300


export default function App() {
  const [hour, setHour] = useState(23)
  const [detour, setDetour] = useState(20)
  const [policy, setPolicy] = useState('neutral')
  const [from, setFrom] = useState(DEFAULT_JOURNEY.from)
  const [to, setTo] = useState(DEFAULT_JOURNEY.to)
  const [journey, setJourney] = useState({
    from: DEFAULT_JOURNEY.from,
    to: DEFAULT_JOURNEY.to,
    fromCoords: DEFAULT_JOURNEY.fromCoords,
    toCoords: DEFAULT_JOURNEY.toCoords,
  })
  const [data, setData] = useState(null)
  const [selectedRoute, setSelectedRoute] = useState('safe')
  const [selectedEvidence, setSelectedEvidence] = useState(null)
  const [loading, setLoading] = useState(null)
  const [error, setError] = useState(null)
  const [fromSuggestions, setFromSuggestions] = useState([])
  const [toSuggestions, setToSuggestions] = useState([])
  const [activeSearch, setActiveSearch] = useState(null)
  const searchRequest = useRef(0)
  const searchTimer = useRef(null)
  const [refreshKey, setRefreshKey] = useState(0)

  // Phones only -- the CSS keeps the form permanently open above 720px. On a
  // small screen the search card and the results sheet between them leave a
  // sliver of map, and the map is the product, so the form collapses to a bar
  // showing the current journey until someone wants to change it.
  const [searchOpen, setSearchOpen] = useState(false)

  // Drag-to-collapse for the results sheet. Inert above 720px -- the class it
  // applies has no styles outside the mobile block.
  const sheet = useSheetDrag()

  useEffect(() => {
    if (!journey.fromCoords || !journey.toCoords) return

    let active = true
    const controller = new AbortController()

    // Shown straight away rather than after the debounce, so dragging a
    // slider reads as responsive even though the request has not left yet.
    setLoading(true)
    setError(null)

    const timer = setTimeout(() => {
      getRoute(
        hour,
        detour,
        policy,
        journey.fromCoords,
        journey.toCoords,
        controller.signal
      )
        .then(route => {
          if (!active) return

          setData(route)
          setSelectedRoute('safe')
        })
        .catch(error => {
          // A cancelled request is not a failure -- the user simply moved the
          // slider again before this one came back.
          if (error.name === 'AbortError') return

          console.error(error)
          // The API explains itself -- out-of-area, no path, and so on. Show
          // that instead of a generic banner.
          if (active) setError(error.message)
        })
        .finally(() => {
          if (active) setLoading(false)
        })
    }, ROUTE_DEBOUNCE_MS)

    return () => {
      active = false
      clearTimeout(timer)
      controller.abort()
    }
  }, [hour, detour, policy, journey, refreshKey])

  function applyPreset(preset) {
    setFrom(preset.from)
    setTo(preset.to)
    setFromSuggestions([])
    setToSuggestions([])
    setActiveSearch(null)
    setSelectedEvidence(null)
    setSearchOpen(false)

    setJourney({
      from: preset.from,
      to: preset.to,
      fromCoords: preset.fromCoords,
      toCoords: preset.toCoords,
    })
  }

  async function handleAudited(roadId) {
    // Reload the drawer with the new ground truth, then re-route so the
    // change is visible immediately.
    setSelectedEvidence(await getSegment(roadId))
    setRefreshKey(key => key + 1)
  }

  async function selectSegment(id) {
    try {
      setSelectedEvidence(await getSegment(id))
    } catch (error) {
      console.error(error)
      setError(error.message)
    }
  }

  async function searchPlaces(query, setter) {
    clearTimeout(searchTimer.current)

    if (query.trim().length < 2) {
      setter([])
      return
    }

    const requestId = ++searchRequest.current

    searchTimer.current = setTimeout(async () => {
      try {
        const response = await fetch(
          `https://api.maptiler.com/geocoding/${encodeURIComponent(
            `${query}, New Delhi`
          )}.json?key=${import.meta.env.VITE_MAPTILER_KEY}&country=in&proximity=77.2295,28.6129&types=poi,address&autocomplete=true&limit=8`
        )

        const result = await response.json()

        if (requestId !== searchRequest.current) return

        const candidates = result.features || []

        const enriched = await Promise.all(
          candidates.map(async place => {
            const [lon, lat] = place.geometry.coordinates

            try {
              const reverseResponse = await fetch(
                `https://api.maptiler.com/geocoding/${lon},${lat}.json?key=${import.meta.env.VITE_MAPTILER_KEY}&types=address&limit=1`
              )

              const reverseData = await reverseResponse.json()

              const address =
                reverseData.features?.[0]?.place_name ||
                reverseData.features?.[0]?.text ||
                ''

              return {
                ...place,
                branchAddress: address,
              }
            } catch {
              return {
                ...place,
                branchAddress: place.place_name || 'Delhi',
              }
            }
          })
        )

        if (requestId !== searchRequest.current) return

        const unique = []
        const seen = new Set()

        for (const place of enriched) {
          const [lon, lat] = place.geometry.coordinates

          const key =
            `${place.text}|` +
            `${lon.toFixed(5)}|` +
            `${lat.toFixed(5)}`

          if (seen.has(key)) continue

          seen.add(key)
          unique.push(place)
        }

        setter(unique.slice(0, 6))
      } catch (error) {
        console.error(error)

        if (requestId === searchRequest.current) {
          setter([])
        }
      }
    }, 350)
  }

  function getDistanceKm(place) {
    const [lon, lat] = place.geometry.coordinates

    const refLon = 77.2295
    const refLat = 28.6129

    const latDiff = (lat - refLat) * 111
    const lonDiff =
      (lon - refLon) *
      111 *
      Math.cos((refLat * Math.PI) / 180)

    return Math.sqrt(
      latDiff * latDiff +
      lonDiff * lonDiff
    )
  }

  async function findRoute(event) {
    event.preventDefault()

    const fromPlace = from.trim() || DEFAULT_JOURNEY.from
    const toPlace = to.trim() || DEFAULT_JOURNEY.to

    try {
      setLoading(true)
      setError(null)

      const [fromResponse, toResponse] = await Promise.all([
        fetch(
          `https://api.maptiler.com/geocoding/${encodeURIComponent(
            `${fromPlace}, New Delhi`
          )}.json?key=${import.meta.env.VITE_MAPTILER_KEY}&country=in&proximity=77.2295,28.6129&types=poi,address&limit=1`
        ),
        fetch(
          `https://api.maptiler.com/geocoding/${encodeURIComponent(
            `${toPlace}, New Delhi`
          )}.json?key=${import.meta.env.VITE_MAPTILER_KEY}&country=in&proximity=77.2295,28.6129&types=poi,address&limit=1`
        ),
      ])

      const fromData = await fromResponse.json()
      const toData = await toResponse.json()

      if (!fromData.features?.length || !toData.features?.length) {
        throw new Error('We could not find one of those places in Delhi.')
      }

      const [fromLon, fromLat] =
        fromData.features[0].geometry.coordinates

      const [toLon, toLat] =
        toData.features[0].geometry.coordinates

      setJourney({
        from: fromPlace,
        to: toPlace,
        fromCoords: {
          lat: fromLat,
          lon: fromLon,
        },
        toCoords: {
          lat: toLat,
          lon: toLon,
        },
      })

      // Collapse on success only. If the geocode failed the form stays open,
      // because the next thing the user needs is to correct what they typed.
      setSearchOpen(false)
    } catch (error) {
      console.error(error)
      setError(error.message)
      setLoading(false)
    }
  }

  return <main className="app-shell">
    {data ? <MapView
      data={data}
      selected={selectedRoute}
      selectedSegment={selectedEvidence?.road_id ?? null}
      onSegment={selectSegment}
      fromCoords={journey.fromCoords}
      toCoords={journey.toCoords}
      fromName={journey.from}
      toName={journey.to}
    /> : !error && <MapSkeleton />}
    <Header />

    {/* Hidden above 720px, where the form is always visible anyway. */}
    <button
      type="button"
      className="search-toggle"
      aria-expanded={searchOpen}
      aria-controls="route-search-form"
      onClick={() => setSearchOpen(open => !open)}
    >
      <span className="search-toggle-route">
        <b>{journey.from}</b>
        <i aria-hidden="true">&rarr;</i>
        <b>{journey.to}</b>
      </span>

      <span className="search-toggle-action">
        {searchOpen ? 'Close' : 'Change'}
      </span>
    </button>

    <form
      id="route-search-form"
      className={searchOpen ? 'route-search open' : 'route-search'}
      onSubmit={findRoute}
      aria-label="Find a safer route"
    >
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: 4,
          marginBottom: 10,
        }}
      >
        <span
          style={{
            fontSize: 9,
            letterSpacing: '0.08em',
            opacity: 0.4,
            flex: '0 0 auto',
          }}
        >
          TRY
        </span>

        {PRESETS.map(preset => {
          const isActive =
            journey.from === preset.from && journey.to === preset.to

          return (
            <button
              type="button"
              key={preset.label}
              onClick={() => applyPreset(preset)}
              style={{
                flex: '0 0 auto',
                whiteSpace: 'nowrap',
                padding: '3px 8px',
                fontSize: 10,
                lineHeight: 1.5,
                fontFamily: 'inherit',
                borderRadius: 999,
                border: `1px solid ${isActive ? '#222522' : 'rgba(0,0,0,0.16)'}`,
                background: isActive ? '#222522' : '#fff',
                color: isActive ? '#fff' : '#222522',
                cursor: 'pointer',
              }}
            >
              {preset.label}
            </button>
          )
        })}
      </div>

      <div
        className="place-field"
        style={{ position: 'relative' }}
      >
        <label htmlFor="from">FROM</label>

        <input
          id="from"
          value={from}
          onFocus={() => setActiveSearch('from')}
          onChange={e => {
            const value = e.target.value
            setFrom(value)

            setJourney(prev => ({
              ...prev,
              fromCoords: null,
            }))

            searchPlaces(value, setFromSuggestions)
          }}
        />

        {activeSearch === 'from' && fromSuggestions.length > 0 && (
          <div className="place-suggestions">
            {fromSuggestions.map(place => {
              const [lon, lat] = place.geometry.coordinates

              return (
                <button
                  type="button"
                  key={place.id}
                  className="place-suggestion"
                  onClick={() => {
                    setFrom(place.place_name || place.text)

                    setJourney(prev => ({
                      ...prev,
                      from: place.place_name || place.text,
                      fromCoords: {
                        lat,
                        lon,
                      },
                    }))

                    setFromSuggestions([])
                    setActiveSearch(null)
                  }}
                >
                  <strong>{place.text}</strong>

                  <small>
                    {place.branchAddress || place.place_name}
                    {' · '}
                    {getDistanceKm(place).toFixed(1)} km away
                  </small>
                </button>
              )
            })}
          </div>
        )}
      </div>
      <span className="search-connector" aria-hidden="true">&darr;</span>
      <div
        className="place-field"
        style={{ position: 'relative' }}
      >
        <label htmlFor="to">TO</label>

        <input
          id="to"
          value={to}
          onFocus={() => setActiveSearch('to')}
          onChange={e => {
            const value = e.target.value
            setTo(value)

            setJourney(prev => ({
              ...prev,
              toCoords: null,
            }))

            searchPlaces(value, setToSuggestions)
          }}
        />

        {activeSearch === 'to' && toSuggestions.length > 0 && (
          <div className="place-suggestions">
            {toSuggestions.map(place => {
              const [lon, lat] = place.geometry.coordinates

              return (
                <button
                  type="button"
                  key={place.id}
                  className="place-suggestion"
                  onClick={() => {
                    setTo(place.place_name || place.text)

                    setJourney(prev => ({
                      ...prev,
                      to: place.place_name || place.text,
                      toCoords: {
                        lat,
                        lon,
                      },
                    }))

                    setToSuggestions([])
                    setActiveSearch(null)
                  }}
                >
                  <strong>{place.text}</strong>

                  <small>
                    {place.branchAddress || place.place_name}
                    {' · '}
                    {getDistanceKm(place).toFixed(1)} km away
                  </small>
                </button>
              )
            })}
          </div>
        )}
      </div>
      <button className="find-route" type="submit">Find safer route <span>&rarr;</span></button>
    </form>
    <aside
      className={`route-panel ${sheet.className}`.trim()}
      style={sheet.style}
    >
      {/* Hidden above 720px. Drag it down to get the map back, up to read
          the detail; a tap toggles, for people who don't think to drag. */}
      <button
        type="button"
        className="sheet-handle"
        aria-expanded={!sheet.collapsed}
        aria-label={
          sheet.collapsed ? 'Expand route details' : 'Collapse route details'
        }
        {...sheet.handleProps}
      />
      {loading && <div className="quiet-loading">Updating route <i /></div>}
      {error && (
        <div className="quiet-error">
          {error}
        </div>
      )}
      {data && (() => {
        const coverage = Math.min(
          data.baseline_route.metrics.coverage_ratio ?? 0,
          data.chiraag_route.metrics.coverage_ratio ?? 0
        )
        const coveragePct = Math.round(coverage * 100)

        // The shortest path was already the least-exposed one, so there is no
        // safer alternative to offer. Saying that plainly beats rendering
        // "0 m less unlit road for only 0 m extra", which reads as a failure
        // when it is actually a finding.
        const noSaferOption =
          data.evidence_summary.unlit_meters_avoided <= 0 &&
          data.evidence_summary.extra_distance_m <= 0

        return <>
        <div className="recommendation">
          <p className="eyebrow">CHIRAAG RECOMMENDS</p>
          <div className="recommendation-title">
            {noSaferOption ? 'Shortest route' : 'Safer route'}
          </div>
          <div className="route-duration">
            {Math.round(data.chiraag_route.metrics.total_length_m)} m
          </div>

          {noSaferOption ? (
            <div className="metric-caveat" style={{ marginTop: 12 }}>
              {coveragePct > 0
                ? `No detour within your ${detour}% budget lowers unlit exposure here, so the shortest route is also the least exposed. We have lighting evidence on ${coveragePct}% of it.`
                : `We have no lighting evidence on this route, so CHIRAAG will not claim one way is safer than another. This is the shortest path.`}
            </div>
          ) : (
            <HeroMetric
              delta={{
                extra_m: data.evidence_summary.extra_distance_m,
                extra_pct:
                  data.baseline_route.metrics.total_length_m > 0
                    ? (
                      (data.evidence_summary.extra_distance_m /
                        data.baseline_route.metrics.total_length_m) *
                      100
                    ).toFixed(1)
                    : 0,
                dark_avoided_m: data.evidence_summary.unlit_meters_avoided,
              }}
              coverage={coverage}
            />
          )}
          <button className="use-route" onClick={() => setSelectedRoute('safe')}>Use this route <span>&rarr;</span></button>
        </div>
        <RouteComparison data={data} selected={selectedRoute} onSelect={setSelectedRoute} />
        <div className="compact-controls"><TimeControl hour={hour} onChange={setHour} /><DetourControl value={detour} onChange={setDetour} /></div>
        <UnknownPolicyControl policy={policy} onChange={setPolicy} />
        </>
      })()}
      <div className="panel-footer"><span className="status-indicator">{USE_MOCK_DATA ? 'LOCAL DEMO DATA' : 'LIVE DATA'}</span><span>Click a street for proof</span></div>
    </aside>
    <EvidencePanel evidence={selectedEvidence} onClose={() => setSelectedEvidence(null)} onAudited={handleAudited} />
  </main>
}