import { useEffect, useState } from 'react';

/**
 * Header component
 */

export function Header() {
  const githubUrl = import.meta.env.VITE_GITHUB_URL || 'https://github.com/Samfresh-ai/ROMA-debug-override';
  const taglines = [
    'Gemini‑Powered',
    'Traceback → Fix',
    'Call Chain Insight',
    'PR Ready Output',
  ];
  const [taglineIndex, setTaglineIndex] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setTaglineIndex((prev) => (prev + 1) % taglines.length);
    }, 2400);
    return () => clearInterval(id);
  }, []);

  return (
    <header className="py-6">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-3">
              <div
                key={taglineIndex}
                className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/80 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-slate-500 transition-opacity duration-500"
              >
                {taglines[taglineIndex]}
              </div>
            </div>
            <h1 className="text-3xl sm:text-4xl font-semibold text-slate-900">
              ROMA Debug
            </h1>
            <p className="text-sm sm:text-base text-slate-600 max-w-xl">
              Investigation‑first debugging that reads real code, traces the root cause, and ships a fix you can trust.
            </p>
          </div>
          <a
            href={githubUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="group inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/80 px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:border-slate-300 hover:text-slate-900"
          >
            <svg className="w-5 h-5 text-slate-500 group-hover:text-slate-800" fill="currentColor" viewBox="0 0 24 24">
              <path
                fillRule="evenodd"
                d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
                clipRule="evenodd"
              />
            </svg>
            GitHub
          </a>
        </div>
      </div>
    </header>
  );
}
