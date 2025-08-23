import { useEffect } from 'react';

export function useHotkeys(map: Record<string, () => void>) {
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      const combo: string[] = [];
      if (e.metaKey || e.ctrlKey) combo.push('ctrl');
      if (e.shiftKey) combo.push('shift');
      if (e.altKey) combo.push('alt');
      combo.push(e.key.toLowerCase());
      const key = combo.join('+');
      const fn = map[key];
      if (fn) {
        e.preventDefault();
        fn();
      }
    }
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [map]);
}
