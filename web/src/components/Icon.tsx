/** A handful of 24px stroke icons drawn for this app — no icon library. */
export type IconName = 'home' | 'phone' | 'agents' | 'book' | 'plug' | 'list' | 'chart'

const PATHS: Record<IconName, string> = {
  home: 'M4 11l8-7 8 7M6 9.5V20h12V9.5M10 20v-6h4v6',
  phone:
    'M5 4h3l2 5-2.5 1.5a11 11 0 0 0 6 6L15 14l5 2v3a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2',
  agents: 'M12 4v5M12 9l-6 6M12 9v6M12 9l6 6M4 15h4v4H4zM10 15h4v4h-4zM16 15h4v4h-4z',
  book: 'M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h10',
  plug: 'M9 3v5M15 3v5M7 8h10v3a5 5 0 0 1-10 0zM12 16v5',
  list: 'M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01',
  chart: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
}

export function Icon({ name }: { name: IconName }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={PATHS[name]} />
    </svg>
  )
}
