// Speaking the question: the server's clip when it has one (the same voice for everyone with a
// server voice), else the browser's own voice. Resolves when speaking ends (or fails, or takes
// far too long), so the think time starts at the same moment for everyone. The question text is
// always on screen as well.

import type { QuestionSpeech } from "@/lib/api";

let current: HTMLAudioElement | null = null;

function browserVoice(text: string): Promise<void> {
  return new Promise((resolve) => {
    const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
    if (!synth || !text) return resolve();
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1;
    u.onend = () => resolve();
    u.onerror = () => resolve();
    synth.speak(u);
  });
}

function withLimit(work: Promise<void>, text: string): Promise<void> {
  const words = text.split(/\s+/).length;
  const limit = Math.max(10, words * 0.7 + 5) * 1000; // never wait forever on a stuck voice
  return Promise.race([work, new Promise<void>((r) => setTimeout(r, limit))]);
}

export function speak(speech: QuestionSpeech | undefined, text: string): Promise<void> {
  cancelSpeech();
  if (speech?.url) {
    const audio = new Audio(speech.url);
    current = audio;
    const played = new Promise<void>((resolve) => {
      audio.onended = () => resolve();
      audio.onerror = () => void browserVoice(text).then(resolve);
      audio.play().catch(() => void browserVoice(text).then(resolve));
    });
    return withLimit(played, text);
  }
  return withLimit(browserVoice(speech?.text || text), text);
}

export function cancelSpeech(): void {
  current?.pause();
  current = null;
  if (typeof window !== "undefined") window.speechSynthesis?.cancel();
}
