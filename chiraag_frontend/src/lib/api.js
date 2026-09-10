const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
export const USE_MOCK_DATA = false

export async function getRoute(
  hour,
  detour,
  unknownPolicy,
  fromCoords,
  toCoords,
  // Passed by the caller so a request superseded by a newer one can be
  // cancelled rather than left to finish and be thrown away. Routing is the
  // expensive endpoint -- every abandoned call still rebuilds the graph.
  signal
) {
  if (!fromCoords || !toCoords) {
    throw new Error('Origin and destination coordinates are required')
  }

  const alpha = 1 + Number(detour) / 100

  const response = await fetch(`${BASE_URL}/api/v1/route`, {
    method: 'POST',
    signal,
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      origin: {
        lat: fromCoords.lat,
        lon: fromCoords.lon,
      },
      destination: {
        lat: toCoords.lat,
        lon: toCoords.lon,
      },
      alpha,
      unknown_policy: unknownPolicy,
      hour: Number(hour),
    }),
  })

  if (!response.ok) {
    let message = 'Route data unavailable'

    try {
      const body = await response.json()

      if (body?.detail) {
        message = typeof body.detail === 'string'
          ? body.detail
          : body.detail[0]?.msg || message
      }
    } catch {
      // non-JSON error body, keep the fallback
    }

    throw new Error(message)
  }

  return response.json()
}

export async function postAudit(
  roadSegmentId,
  rating,
  observedLightCount = 0
) {
  const response = await fetch(`${BASE_URL}/api/v1/evidence/audit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      road_segment_id: roadSegmentId,
      rating,
      observed_light_count: observedLightCount,
    }),
  })

  if (!response.ok) {
    throw new Error('Could not record your audit')
  }

  return response.json()
}

export async function getSegment(id) {
  const response = await fetch(
    `${BASE_URL}/api/v1/evidence/segment/${id}`
  )

  if (!response.ok) {
    throw new Error('Segment data unavailable')
  }

  return response.json()
}