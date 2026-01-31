import { useEffect, useRef, useState } from 'react';
import Prism from 'prismjs';
import 'prismjs/themes/prism-tomorrow.css';
import 'prismjs/components/prism-python';
import 'prismjs/components/prism-javascript';
import 'prismjs/components/prism-typescript';

interface FixDisplayProps {
  fix: string;
}

/**
 * Component to display the code fix with syntax highlighting
 */
export function FixDisplay({ fix }: FixDisplayProps) {
  const codeRef = useRef<HTMLElement>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (codeRef.current) {
      Prism.highlightElement(codeRef.current);
    }
  }, [fix]);

  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(fix);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  // Try to detect language from content
  const detectLanguage = (code: string): string => {
    if (code.includes('def ') || code.includes('import ') || code.includes('class ')) {
      return 'python';
    }
    if (code.includes('function ') || code.includes('const ') || code.includes('let ')) {
      return 'javascript';
    }
    return 'python'; // Default to python
  };

  const language = detectLanguage(fix);

  return (
    <div className="bg-gray-900 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
        <span className="text-sm text-gray-400 font-medium">Code Fix</span>
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
            {fix}
          </code>
        </pre>
      </div>
    </div>
  );
}
