/**
 * Visual simulation clock for the 3D twin.
 *
 * The sim-orchestrator publishes discrete ticks (≥ 1 simulated minute each).
 * Between ticks the scene extrapolates at the source speed multiplier so
 * motion is smooth, but never further than `maxLead` beyond the last tick:
 * if the source stalls, the scene stops instead of inventing future state.
 * A paused source freezes the scene exactly at the last observed tick.
 */
export interface ClockAnchor {
  /** Last observed simulation time (epoch seconds). */
  sim: number;
  /** Wall time (performance.now ms) when that tick was observed. */
  wall: number;
  speed: number;
  paused: boolean;
}

/** Extrapolation ceiling: two wall-seconds at the source speed, at least one tick step. */
export const maxLead = (speed: number) => Math.max(60, Math.max(0, speed) * 2);

export function simSecondsAt(anchor: ClockAnchor, wallMs: number, reducedMotion = false): number {
  if (anchor.paused || reducedMotion) return anchor.sim;
  const lead = (wallMs - anchor.wall) / 1000 * Math.max(0, anchor.speed);
  return anchor.sim + Math.min(Math.max(0, lead), maxLead(anchor.speed));
}

/**
 * Keeps displayed time monotonic across ticks: when a new tick lands slightly
 * behind what was already extrapolated, hold until real time catches up.
 * A genuine backwards jump in the source (reset/restore) is followed.
 */
export class VisualClock {
  private anchor: ClockAnchor | null = null;
  private shown = -Infinity;

  observe(sim: number | null, wallMs: number, speed: number, paused: boolean) {
    if (sim === null) return;
    const previous = this.anchor;
    if (previous && previous.sim === sim && previous.paused === paused && previous.speed === speed) return;
    // A pause freezes at the source's last tick, not at an extrapolated time.
    if (paused || sim < this.shown - maxLead(speed)) this.shown = paused ? sim : -Infinity;
    // Same tick re-observed with a new speed/pause state: re-anchor at the
    // time currently shown so the change neither jumps nor rewinds.
    if (previous && previous.sim === sim && !paused) this.anchor = { sim: Math.max(sim, this.shown === -Infinity ? sim : this.shown), wall: wallMs, speed, paused };
    else this.anchor = { sim, wall: wallMs, speed, paused };
  }

  now(wallMs: number, reducedMotion = false): number | null {
    if (!this.anchor) return null;
    const value = simSecondsAt(this.anchor, wallMs, reducedMotion);
    this.shown = Math.max(this.shown, value);
    return this.anchor.paused || reducedMotion ? value : this.shown;
  }
}
