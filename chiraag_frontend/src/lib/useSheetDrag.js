import { useCallback, useRef, useState } from 'react'

// How far the sheet has to travel before it snaps to the other state. Below
// this it springs back, so a thumb that slips while scrolling doesn't dismiss
// the panel someone was reading.
const SNAP_DISTANCE_PX = 80

// Under this the gesture never really moved, so treat it as a tap. Lets the
// handle work for people who expect to tap it rather than drag.
const TAP_SLOP_PX = 6

/**
 * Drag-to-collapse behaviour for a bottom sheet.
 *
 * Returns a class name and a CSS custom property for the sheet, plus pointer
 * handlers for its grab handle. The actual movement is CSS -- this only tracks
 * how far the finger has gone and which side of the snap threshold it ended
 * on, so dragging stays at the compositor's frame rate rather than React's.
 *
 * Pointer events rather than touch events, so a mouse on a narrow window
 * behaves the same as a finger.
 */
export function useSheetDrag(initiallyCollapsed = false) {
  const [collapsed, setCollapsed] = useState(initiallyCollapsed)
  const [drag, setDrag] = useState(0)
  const [dragging, setDragging] = useState(false)

  const origin = useRef(null)

  const onPointerDown = useCallback(event => {
    origin.current = { y: event.clientY, collapsed }
    setDragging(true)

    // Keeps move events coming even if the finger leaves the handle.
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }, [collapsed])

  const onPointerMove = useCallback(event => {
    if (!origin.current) return

    const travelled = event.clientY - origin.current.y

    // An open sheet can only be pulled down and a collapsed one only up.
    // Without this it detaches from the bottom of the screen and floats.
    setDrag(
      origin.current.collapsed
        ? Math.min(0, travelled)
        : Math.max(0, travelled)
    )
  }, [])

  const onPointerFinish = useCallback(event => {
    if (!origin.current) return

    const travelled = event.clientY - origin.current.y
    const wasCollapsed = origin.current.collapsed

    origin.current = null
    setDragging(false)
    setDrag(0)

    if (Math.abs(travelled) < TAP_SLOP_PX) {
      setCollapsed(value => !value)
      return
    }

    if (wasCollapsed && travelled < -SNAP_DISTANCE_PX) {
      setCollapsed(false)
    } else if (!wasCollapsed && travelled > SNAP_DISTANCE_PX) {
      setCollapsed(true)
    }
  }, [])

  return {
    collapsed,
    setCollapsed,

    className: [collapsed && 'collapsed', dragging && 'dragging']
      .filter(Boolean)
      .join(' '),

    // Read by the stylesheet so the sheet follows the finger while the
    // snap-back transition stays in CSS.
    style: { '--drag': `${drag}px` },

    handleProps: {
      onPointerDown,
      onPointerMove,
      onPointerUp: onPointerFinish,
      onPointerCancel: onPointerFinish,
    },
  }
}
