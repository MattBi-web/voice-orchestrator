/** An agent's avatar: a small lit sphere whose colors come from its id, so
 * the same agent always looks the same and two agents rarely look alike.
 * Hues are drawn from the app's own families (slate, teal, amber, blue,
 * violet), soft enough to sit next to the router-level colors. */
const HUES = [205, 178, 36, 222, 262, 150, 12]

function hash(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

export function Orb({ seed, size = 22 }: { seed: string; size?: number }) {
  const h = hash(seed || '?')
  const a = HUES[h % HUES.length]
  const b = HUES[(h >>> 3) % HUES.length]
  const x = 25 + ((h >>> 6) % 30)
  const y = 20 + ((h >>> 11) % 25)
  return (
    <span
      className="orb"
      aria-hidden
      style={{
        width: size,
        height: size,
        background: `radial-gradient(circle at ${x}% ${y}%, hsl(${a} 70% 88%) 0%, hsl(${a} 45% 62%) 38%, hsl(${b} 40% 32%) 78%, hsl(${b} 35% 18%) 100%)`,
      }}
    />
  )
}
