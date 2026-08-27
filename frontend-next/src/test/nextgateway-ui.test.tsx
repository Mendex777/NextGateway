import { afterEach, describe, expect, it, vi } from 'vitest';

import { copyText, mapConcurrent } from '../nextgateway/ui';

describe('NextGateway UI helpers', () => {
  afterEach(() => vi.restoreAllMocks());

  it('uses the Clipboard API when it is available', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });

    await copyText('vless://example');

    expect(writeText).toHaveBeenCalledWith('vless://example');
  });

  it('falls back to execCommand on an insecure LAN origin', async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand });

    await copyText('https://subscription.example');

    expect(execCommand).toHaveBeenCalledWith('copy');
    expect(document.querySelector('textarea')).toBeNull();
  });

  it('runs probes concurrently without exceeding the limit', async () => {
    let active = 0;
    let maximum = 0;
    const completed: number[] = [];
    await mapConcurrent([1, 2, 3, 4, 5], 2, async (item) => {
      active += 1;
      maximum = Math.max(maximum, active);
      await new Promise((resolve) => setTimeout(resolve, 5));
      completed.push(item);
      active -= 1;
    });

    expect(maximum).toBe(2);
    expect(completed.sort()).toEqual([1, 2, 3, 4, 5]);
  });
});
