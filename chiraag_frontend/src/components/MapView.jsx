import React, { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'


const API_KEY = import.meta.env.VITE_MAPTILER_KEY

const STREET_STYLE =
  `https://api.maptiler.com/maps/streets-v4/style.json?key=${API_KEY}`

const SATELLITE_STYLE =
  `https://api.maptiler.com/maps/satellite/style.json?key=${API_KEY}`


const line = (route) => ({
  type: 'FeatureCollection',
  features: [route],
})

const lineFeature = (coordinates) => ({
  type: 'Feature',
  geometry: {
    type: 'LineString',
    coordinates,
  },
})

// Render the actual geometry of every physical road segment.
// Do NOT connect route nodes directly with straight lines because
// graph nodes represent endpoints/intersections, not the road shape.
const routeGeometryCollection = route => {
  const segments = route?.segments || []

  if (segments.length > 0) {
    return {
      type: 'FeatureCollection',
      features: segments
        .filter(segment => segment.coordinates?.length >= 2)
        .map(segment => ({
          type: 'Feature',
          properties: {
            road_id: segment.road_id,
            observation_state: segment.observation_state,
            dark_fraction: segment.dark_fraction ?? -1,
          },
          geometry: {
            type: 'LineString',
            coordinates: segment.coordinates,
          },
        })),
    }
  }

  // Safe fallback for old/API responses that do not contain segments.
  return line(lineFeature(route?.nodes || []))
}

// One feature per physical street, carrying the evidence needed to colour
// it and to open the drawer when clicked.
const segmentCollection = (route) => ({
  type: 'FeatureCollection',
  features: (route?.segments || [])
    .filter(segment => segment.coordinates?.length >= 2)
    .map(segment => ({
      type: 'Feature',
      properties: {
        road_id: segment.road_id,
        observation_state: segment.observation_state,
        // GeoJSON filters can't match null, so unknown is encoded as -1.
        dark_fraction:
          segment.dark_fraction === null ||
            segment.dark_fraction === undefined
            ? -1
            : segment.dark_fraction,
      },
      geometry: {
        type: 'LineString',
        coordinates: segment.coordinates,
      },
    })),
})

export function MapView({
  data,
  selected,
  selectedSegment,
  onSegment,
  fromCoords,
  toCoords,
  fromName,
  toName,
}) {
  const container = useRef(null)
  const map = useRef(null)
  const markers = useRef([])
  const [satellite, setSatellite] = useState(false)

  // Keep the latest callback and route in refs so the map event handlers,
  // which are registered once, never close over stale props.
  const onSegmentRef = useRef(onSegment)
  const dataRef = useRef(data)
  const selectedRef = useRef(selected)

  useEffect(() => {
    onSegmentRef.current = onSegment
  }, [onSegment])

  useEffect(() => {
    dataRef.current = data
    selectedRef.current = selected
  }, [data, selected])

  const activeRoute = () =>
    selectedRef.current === 'safe'
      ? dataRef.current?.chiraag_route
      : dataRef.current?.baseline_route

  const handleSegmentClick = useRef(event => {
    const feature = event.features?.[0]
    const roadId = feature?.properties?.road_id

    if (roadId !== undefined && roadId !== null) {
      onSegmentRef.current?.(roadId)
    }
  }).current

  const handleSegmentEnter = useRef(event => {
    event.target.getCanvas().style.cursor = 'pointer'
  }).current

  const handleSegmentLeave = useRef(event => {
    event.target.getCanvas().style.cursor = ''
  }).current

  function addChiraagLayers(m) {
    if (!m.getSource('shortest')) {
      m.addSource('shortest', {
        type: 'geojson',
        data: routeGeometryCollection(data.baseline_route),
      })

      m.addLayer({
        id: 'shortest-line',
        type: 'line',
        source: 'shortest',
        paint: {
          'line-color': '#575b58',
          'line-width': selected === 'shortest' ? 6 : 3.5,
          'line-opacity': selected === 'shortest' ? 0.92 : 0.64,
        },
        layout: {
          'line-cap': 'round',
          'line-join': 'round',
        },
      })
    }

    if (!m.getSource('safest')) {
      m.addSource('safest', {
        type: 'geojson',
        data: routeGeometryCollection(data.chiraag_route),
      })

      m.addLayer({
        id: 'safest-line',
        type: 'line',
        source: 'safest',
        paint: {
          'line-color': '#ad7f24',
          'line-width': selected === 'safe' ? 7 : 4.5,
          'line-opacity': selected === 'safe' ? 1 : 0.72,
        },
        layout: {
          'line-cap': 'round',
          'line-join': 'round',
        },
      })
    }

    if (!m.getSource('segments')) {
      m.addSource('segments', {
        type: 'geojson',
        data: segmentCollection(
          selected === 'safe' ? data.chiraag_route : data.baseline_route
        ),
      })

      // Hatching over stretches we have no imagery for. This is what makes
      // "unknown" visible rather than silently blending into the route.
      m.addLayer({
        id: 'segments-unknown',
        type: 'line',
        source: 'segments',
        filter: ['==', ['get', 'observation_state'], 'unobserved'],
        paint: {
          'line-color': '#ffffff',
          'line-width': 2.4,
          'line-opacity': 0.95,
          'line-dasharray': [0.9, 1.5],
        },
        layout: {
          'line-cap': 'butt',
        },
      })

      // Stretches we have positive evidence are mostly unlit. Without this
      // the whole argument lives in the drawer: the map shows two coloured
      // lines and no reason to prefer either. Drawn over the route so the
      // route colour still reads underneath.
      //
      // Unknown segments carry dark_fraction -1, so they cannot match here --
      // "we have not looked" never renders as darkness.
      m.addLayer({
        id: 'segments-dark',
        type: 'line',
        source: 'segments',
        filter: ['>', ['get', 'dark_fraction'], 0.5],
        paint: {
          'line-color': '#151b23',
          'line-width': 3.4,
          'line-opacity': 0.92,
          'line-dasharray': [2, 1.1],
        },
        layout: {
          'line-cap': 'butt',
        },
      })

      // Highlight for whichever street the drawer is showing.
      m.addLayer({
        id: 'segments-selected',
        type: 'line',
        source: 'segments',
        filter: ['==', ['get', 'road_id'], -1],
        paint: {
          'line-color': '#111311',
          'line-width': 10,
          'line-opacity': 0.35,
        },
        layout: {
          'line-cap': 'round',
          'line-join': 'round',
        },
      })

      // Invisible wide hit area. Many segments are under 10 m long, so the
      // clickable target has to be far wider than the drawn line.
      m.addLayer({
        id: 'segments-hit',
        type: 'line',
        source: 'segments',
        paint: {
          'line-color': '#000000',
          'line-width': 22,
          'line-opacity': 0,
        },
      })
    }

    m.off('click', 'segments-hit', handleSegmentClick)
    m.on('click', 'segments-hit', handleSegmentClick)

    m.off('mouseenter', 'segments-hit', handleSegmentEnter)
    m.on('mouseenter', 'segments-hit', handleSegmentEnter)

    m.off('mouseleave', 'segments-hit', handleSegmentLeave)
    m.on('mouseleave', 'segments-hit', handleSegmentLeave)
  }

  function addMarkers(m) {
    markers.current.forEach(marker => marker.remove())
    markers.current = []

    const route = activeRoute()

    if (!route?.nodes?.length) return

    // Use the actual snapped route endpoints rather than the raw
    // geocoded search coordinates. This keeps the markers aligned
    // with the road network used by CHIRAAG.
    const start = route.nodes[0]
    const end = route.nodes[route.nodes.length - 1]

    const points = [
      {
        coords: start,
        color: '#222522',
        popup: fromName,
      },
      {
        coords: end,
        color: '#ad7f24',
        popup: toName,
      },
    ]

    points.forEach(point => {
      const marker = new maplibregl.Marker({
        color: point.color,
      })
        .setLngLat(point.coords)
        .setPopup(
          new maplibregl.Popup({ offset: 22 }).setText(point.popup)
        )
        .addTo(m)

      markers.current.push(marker)
    })
  }

  useEffect(() => {
    if (!container.current || map.current) return

    const m = new maplibregl.Map({
      container: container.current,
      style: STREET_STYLE,
      center: [77.2202, 28.6198],
      zoom: 15.65,
      attributionControl: false,
      pitchWithRotate: false,
      dragRotate: false,
    })

    m.addControl(
      new maplibregl.NavigationControl({
        showCompass: false,
      }),
      'top-right'
    )

    map.current = m

    m.on('load', () => {
      addChiraagLayers(m)
      addMarkers(m)

      const coords = [
        ...data.baseline_route.nodes,
        ...data.chiraag_route.nodes,
      ]

      const bounds = coords.reduce(
        (b, coord) => b.extend(coord),
        new maplibregl.LngLatBounds(coords[0], coords[0])
      )

      m.fitBounds(bounds, {
        padding: 100,
        duration: 0,
      })
    })

    return () => {
      m.off('click', 'segments-hit', handleSegmentClick)
      m.off('mouseenter', 'segments-hit', handleSegmentEnter)
      m.off('mouseleave', 'segments-hit', handleSegmentLeave)

      markers.current.forEach(marker => marker.remove())
      markers.current = []
      m.remove()
      map.current = null
    }
  }, [])

  useEffect(() => {
    const m = map.current

    if (!m || !m.isStyleLoaded()) return

    m.getSource('shortest')?.setData(
      routeGeometryCollection(data.baseline_route)
    )

    m.getSource('safest')?.setData(
      routeGeometryCollection(data.chiraag_route)
    )

    m.getSource('segments')?.setData(
      segmentCollection(activeRoute())
    )

    // Reposition the origin/destination markers to the
    // currently active route's snapped endpoints.
    addMarkers(m)

    m.setPaintProperty(
      'shortest-line',
      'line-width',
      selected === 'shortest' ? 6 : 3.5
    )

    m.setPaintProperty(
      'shortest-line',
      'line-opacity',
      selected === 'shortest' ? 0.92 : 0.64
    )

    m.setPaintProperty(
      'safest-line',
      'line-width',
      selected === 'safe' ? 7 : 4.5
    )

    m.setPaintProperty(
      'safest-line',
      'line-opacity',
      selected === 'safe' ? 1 : 0.72
    )
  }, [data, selected])

  useEffect(() => {
    const m = map.current

    if (!m || !m.isStyleLoaded() || !m.getLayer('segments-selected')) return

    m.setFilter('segments-selected', [
      '==',
      ['get', 'road_id'],
      selectedSegment ?? -1,
    ])
  }, [selectedSegment])

  function switchStyle() {
    const m = map.current

    if (!m) return

    const nextSatellite = !satellite

    setSatellite(nextSatellite)

    m.once('style.load', () => {
      addChiraagLayers(m)
      addMarkers(m)

      if (selectedSegment !== null && selectedSegment !== undefined) {
        m.setFilter('segments-selected', [
          '==',
          ['get', 'road_id'],
          selectedSegment,
        ])
      }
    })

    m.setStyle(
      nextSatellite
        ? SATELLITE_STYLE
        : STREET_STYLE
    )
  }

  return (
    <div ref={container} className="map-canvas">
      <div className="route-chip">
        <i className={selected === 'safe' ? 'gold' : 'grey'} />

        {selected === 'safe'
          ? 'Safer route selected'
          : 'Shortest route selected'}
      </div>

      {/* Styled in globals.css rather than inline, so the mobile layout can
          move it -- an inline style cannot be overridden by a media query. */}
      <div className="basemap-toggle">
        <button
          type="button"
          className={satellite ? '' : 'active'}
          onClick={() => {
            if (satellite) switchStyle()
          }}
        >
          Map
        </button>

        <button
          type="button"
          className={satellite ? 'active' : ''}
          onClick={() => {
            if (!satellite) switchStyle()
          }}
        >
          Satellite
        </button>
      </div>

      <div className="map-legend">
        <span>
          <i className="legend-safe" /> Safer
        </span>

        <span>
          <i className="legend-short" /> Shortest
        </span>

        <span>
          <i className="legend-dark" /> Unlit stretch
        </span>

        <span>
          <i className="legend-unknown" /> Limited observation
        </span>
      </div>

      <div className="map-attribution">
        © OpenStreetMap contributors &nbsp; | &nbsp; © MapTiler
      </div>
    </div>
  )
}