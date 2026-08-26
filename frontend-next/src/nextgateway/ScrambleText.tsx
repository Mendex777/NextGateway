import { useEffect, useRef } from 'react';

const GLYPHS = '—~±§|[].+$^@*()•x%!?#';

export default function ScrambleText({ children }: { children: string }) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const started = performance.now();
    const duration = 620;
    let frame = 0;
    const draw = (now: number) => {
      const progress = Math.min(1, (now - started) / duration);
      const fixed = Math.floor(children.length * progress * progress);
      element.textContent = Array.from(children, (char, index) => {
        if (char === ' ' || index < fixed) return char;
        return GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
      }).join('');
      if (progress < 1) frame = requestAnimationFrame(draw);
      else element.textContent = children;
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [children]);

  return <span ref={ref}>{children}</span>;
}

