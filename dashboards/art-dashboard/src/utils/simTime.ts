/** Legacy simulator timestamps without offsets represent UTC, never local time. */
export function parseSimTime(value: string): Date {
  return new Date(/Z$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
}
