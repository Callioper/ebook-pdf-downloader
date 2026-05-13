/** Play a two-tone ascending chime (C5 → E5) for notifications. */
export function playNotificationSound() {
  try {
    const ctx = new AudioContext()
    const now = ctx.currentTime
    const duration = 0.6
    ;[523.25, 659.25].forEach((freq, i) => {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'sine'
      osc.frequency.value = freq
      gain.gain.setValueAtTime(0.3, now + i * 0.15)
      gain.gain.exponentialRampToValueAtTime(0.01, now + i * 0.15 + 0.3)
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.start(now + i * 0.15)
      osc.stop(now + i * 0.15 + 0.3)
      if (i === 1) osc.onended = () => ctx.close()
    })
  } catch {
    // Audio not available — silently ignore
  }
}
