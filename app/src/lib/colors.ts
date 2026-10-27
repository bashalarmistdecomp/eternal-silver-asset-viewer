// A colour of its own for each of the sixteen MIDI channels, all in one
// register. Lanes 17-32 (a second port, as Square's AKAO uses) take
// lighter partners of the first.
export const CHANNEL_COLORS = [
  '#2d8a2d', '#2b6cb0', '#b08825', '#8b46cc', '#c53030', '#dd6b20', '#2c9a9a', '#d53f8c',
  '#718096', '#5a8f29', '#3c5aa6', '#a0522d', '#6b46c1', '#b7791f', '#319795', '#97266d',
  '#4fae4f', '#4a8fd6', '#cfa847', '#a96fe0', '#e05656', '#f08a45', '#4cbcbc', '#e866a8',
  '#94a3b8', '#7fb34a', '#6683cc', '#c4774f', '#8f6fe0', '#d69a3a', '#45b3b0', '#b84a8e',
]

export function channelColor(channel: number): string {
  return CHANNEL_COLORS[channel % CHANNEL_COLORS.length]
}
