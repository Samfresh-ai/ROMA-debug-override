/**
 * API client for ROMA Debug backend
 */

export interface AnalyzeRequest {
  log: string;
  context?: string;
}

export interface AnalyzeResponse {
  fix: string;
}

export interface HealthResponse {
  status: string;
  version: string;
}

/**
 * Check API health
 */
export async function checkHealth(): Promise<HealthResponse> {
  const response = await fetch('/health');
  if (!response.ok) {
    throw new Error('API health check failed');
  }
  return response.json();
}

/**
 * Analyze an error log and get a fix
 */
export async function analyzeError(log: string, context?: string): Promise<AnalyzeResponse> {
  const response = await fetch('/analyze', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ log, context: context || '' }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Analysis failed');
  }

  return response.json();
}
