import { useState } from 'react';

interface LogPasteAreaProps {
  onSubmit: (log: string) => void;
  isLoading: boolean;
}

/**
 * Text area for pasting error logs
 */
export function LogPasteArea({ onSubmit, isLoading }: LogPasteAreaProps) {
  const [log, setLog] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (log.trim()) {
      onSubmit(log.trim());
    }
  };

  const handleClear = () => {
    setLog('');
  };

  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText();
      setLog(text);
    } catch (err) {
      console.error('Failed to read clipboard:', err);
    }
  };

  const loadExample = () => {
    setLog(`Traceback (most recent call last):
  File "/app/src/main.py", line 42, in main
    result = process_user_data(user_input)
  File "/app/src/processor.py", line 15, in process_user_data
    validated = validate_input(data)
  File "/app/src/validator.py", line 28, in validate_input
    if len(data["items"]) > MAX_ITEMS:
TypeError: object of type 'NoneType' has no len()`);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <div className="flex justify-between items-center mb-2">
          <label htmlFor="error-log" className="block text-sm font-semibold text-slate-700">
            Error Log
          </label>
          <button
            type="button"
            onClick={loadExample}
            className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500 hover:text-slate-700"
          >
            Load Example
          </button>
        </div>
        <textarea
          id="error-log"
          value={log}
          onChange={(e) => setLog(e.target.value)}
          placeholder="Paste your error log or traceback here..."
          className="w-full h-64 px-4 py-3 border border-slate-200 rounded-xl shadow-sm
                     focus:ring-2 focus:ring-blue-500 focus:border-blue-500
                     font-mono text-sm resize-none
                     placeholder:text-slate-400 bg-white"
          disabled={isLoading}
        />
      </div>

      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex space-x-2">
          <button
            type="button"
            onClick={handlePaste}
            disabled={isLoading}
            className="px-4 py-2 text-xs font-semibold uppercase tracking-[0.15em] text-slate-700 bg-white
                       border border-slate-200 rounded-full shadow-sm
                       hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed
                       transition-colors"
          >
            Paste
          </button>
          <button
            type="button"
            onClick={handleClear}
            disabled={isLoading || !log}
            className="px-4 py-2 text-xs font-semibold uppercase tracking-[0.15em] text-slate-700 bg-white
                       border border-slate-200 rounded-full shadow-sm
                       hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed
                       transition-colors"
          >
            Clear
          </button>
        </div>

        <button
          type="submit"
          disabled={isLoading || !log.trim()}
          className="px-6 py-2 text-sm font-semibold text-white bg-blue-600
                     rounded-full shadow-sm hover:bg-blue-700
                     disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isLoading ? (
            <span className="flex items-center">
              <svg
                className="animate-spin -ml-1 mr-2 h-4 w-4 text-white"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
              Analyzing...
            </span>
          ) : (
            'Get Fix'
          )}
        </button>
      </div>
    </form>
  );
}
