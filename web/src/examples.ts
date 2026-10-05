/** Things a caller might say to the demo family (Italian), with an English
 * gloss. Shared by the Overview's router demo and the call page. */
export const EXAMPLES: { text: string; gloss: string }[] = [
  { text: 'Quanto costa il roaming in Francia?', gloss: 'roaming prices in France' },
  { text: 'Ho un problema con la bolletta', gloss: 'a problem with my bill' },
  { text: 'Voglio parlare con un operatore', gloss: 'I want a human' },
  { text: 'Il wifi non si connette', gloss: "wifi won't connect" },
]

/** English for the caller's lines in the example call (exampleCall.json). */
export const GLOSSES: Record<string, string> = {
  ...Object.fromEntries(EXAMPLES.map((e) => [e.text, e.gloss])),
  'Perfetto, grazie. Arrivederci': 'great, thanks, goodbye',
}
