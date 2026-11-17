/** Canvas and WebGL cannot read CSS variables. Keep these equal to styles.css. */
export const ACCENT_CYAN = '#3cf0ff';
export const ACCENT_VIOLET = '#c4b5fd';
export const ELECTRODE_MARKER_COLOR = '#9af7ff';

export function markerColor(label: string, selected: string | null, emphasized: readonly string[] = []): string {
  if (selected !== null && label === selected) {
    return ACCENT_VIOLET;
  }
  return emphasized.includes(label) ? ACCENT_VIOLET : ELECTRODE_MARKER_COLOR;
}
