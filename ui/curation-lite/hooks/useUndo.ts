import { useState } from 'react';

export function useUndo<T>(initial: T) {
  const [history, setHistory] = useState<T[]>([initial]);
  const [index, setIndex] = useState(0);

  const state = history[index];

  function setState(next: T) {
    const updated = history.slice(0, index + 1);
    updated.push(next);
    setHistory(updated);
    setIndex(updated.length - 1);
  }

  function undo() {
    if (index > 0) setIndex(index - 1);
  }

  function redo() {
    if (index < history.length - 1) setIndex(index + 1);
  }

  return { state, setState, undo, redo };
}
