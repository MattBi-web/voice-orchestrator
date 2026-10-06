/** 24px stroke icons drawn for this app — no icon library. */
export type IconName =
  | 'home'
  | 'phone'
  | 'agents'
  | 'book'
  | 'plug'
  | 'list'
  | 'chart'
  | 'search'
  | 'plus'
  | 'back'
  | 'sliders'
  | 'flow'
  | 'code'
  | 'user'
  | 'x'
  | 'globe'
  | 'file'
  | 'text'
  | 'webhook'
  | 'server'
  | 'spark'
  | 'external'
  | 'chevron'

const PATHS: Record<IconName, string> = {
  home: 'M4 11l8-7 8 7M6 9.5V20h12V9.5M10 20v-6h4v6',
  phone:
    'M5 4h3l2 5-2.5 1.5a11 11 0 0 0 6 6L15 14l5 2v3a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2',
  agents: 'M9 8a3 3 0 1 0 0-.01M3.5 19a5.5 5.5 0 0 1 11 0M16 5.5a3 3 0 0 1 0 5.8M17.5 14.5a5.5 5.5 0 0 1 3 4.5',
  book: 'M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h10',
  plug: 'M14.5 6.5l3-3M17.5 9.5l3-3M9 9l6 6M7 11l6 6-2 2a4 4 0 0 1-6-6zM4 20l2-2',
  list: 'M4 6h16M4 12h16M4 18h10',
  chart: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4',
  plus: 'M12 5v14M5 12h14',
  back: 'M15 6l-6 6 6 6',
  chevron: 'M9 6l6 6-6 6',
  sliders: 'M4 7h10M18 7h2M4 17h4M12 17h8M14 4v6M8 14v6',
  flow: 'M4 5h6v4H4zM14 15h6v4h-6zM7 9v3a3 3 0 0 0 3 3h4',
  code: 'M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 4l-3 16',
  user: 'M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM4 21a8 8 0 0 1 16 0',
  x: 'M6 6l12 12M18 6L6 18',
  globe: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18',
  file: 'M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6',
  text: 'M5 6V4h14v2M12 4v16M9 20h6',
  webhook: 'M9 8a3 3 0 1 1 5 2.2L11 16M5 17a3 3 0 1 0 5-2h6M19 17a3 3 0 1 0-2.6-4.5L13.5 8',
  server: 'M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01',
  spark: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z',
  external: 'M14 4h6v6M20 4l-9 9M18 14v6H4V6h6',
}

export function Icon({ name, size }: { name: IconName; size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
