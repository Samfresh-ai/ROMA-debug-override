import { useEffect, useRef, useState } from 'react';
import Prism from 'prismjs';
import 'prismjs/themes/prism-tomorrow.css';
import 'prismjs/components/prism-python';
import 'prismjs/components/prism-javascript';
import 'prismjs/components/prism-typescript';

interface FixDisplayProps {
  code: string;
  explanation: string;
  filepath: string | null;
}

/**
 * Component to display the code fix with syntax highlighting
 */
export function FixDisplay({ code, explanation, filepath }: FixDisplayProps) {
  const codeRef = useRef<HTMLElement>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (codeRef.current) {
      Prism.highlightElement(codeRef.current);
    }
  }, [code]);

  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  // Try to detect language from content
  const detectLanguage = (codeStr: string): string => {
    if (codeStr.includes('def ') || codeStr.includes('import ') || codeStr.includes('class ')) {
      return 'python';
    }
    if (codeStr.includes('function ') || codeStr.includes('const ') || codeStr.includes('let ')) {
      return 'javascript';
    }
    return 'python'; // Default to python
  };

  const language = detectLanguage(code);

  return (
    <div className="space-y-4">
      {/* Explanation Section */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <div className="flex items-start">
          <svg className="w-5 h-5 text-blue-500 mr-2 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <div>
            <h3 className="font-medium text-blue-800">Explanation</h3>
            <p className="mt-1 text-blue-700">{explanation}</p>
          </div>
        </div>
      </div>

      {/* Filepath Section */}
      {filepath && (
        <div className="flex items-center text-sm text-gray-600 bg-gray-100 rounded-lg px-4 py-2">
          <svg className="w-4 h-4 mr-2 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          <span className="font-mono">{filepath}</span>
        </div>
      )}

      {/* No Filepath Warning */}
      {!filepath && (
        <div className="flex items-center text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-4 py-2">
          <svg className="w-4 h-4 mr-2 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <span>General advice - no specific file to patch</span>
        </div>
      )}

      {/* Code Section */}
      {code && (
        <div className="bg-gray-900 rounded-lg overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
            <span className="text-sm text-gray-400 font-medium">
              {filepath ? 'Code Fix' : 'Suggested Code'}
            </span>
            <button
              onClick={copyToClipboard}
              className="flex items-center px-3 py-1 text-sm font-medium text-gray-300
                         bg-gray-700 rounded hover:bg-gray-600 transition-colors"
            >
              {copied ? (
                <>
                  <svg className="w-4 h-4 mr-1 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                  Copied!
                </>
              ) : (
                <>
                  <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                          d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
                  </svg>
                  Copy
                </>
              )}
            </button>
          </div>
          <div className="p-4 overflow-x-auto">
            <pre className="!m-0 !p-0 !bg-transparent">
              <code ref={codeRef} className={`language-${language}`}>
                {code}
              </code>
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
