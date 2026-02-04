/**
 * API client for ROMA Debug backend
 */

export interface AnalyzeRequest {
  log: string;
  context?: string;
}

export interface AnalyzeResponse {
  explanation: string;
  code: string;
  filepath: string | null;
  diff?: string | null;
  root_cause_file?: string | null;
  root_cause_explanation?: string | null;
  additional_fixes?: Array<{
    filepath: string;
    code: string;
    explanation: string;
    diff?: string | null;
  }>;
  files_read?: string[];
  files_read_sources?: Record<string, string>;
}

export interface HealthResponse {
  status: string;
  version: string;
}

export interface GithubOAuthStartResponse {
  authorize_url: string;
}

export interface GithubOAuthExchangeResponse {
  session_id: string;
}

export interface GithubCloneResponse {
  repo_id: string;
  repo_path: string;
  default_branch: string;
}

export interface GithubRepoItem {
  full_name: string;
  html_url: string;
  private: boolean;
  default_branch: string;
}

export interface GithubRepoListResponse {
  repos: GithubRepoItem[];
}

export interface GithubAnalyzeResponse extends AnalyzeResponse {}

export interface GithubPrResponse {
  status: string;
  pr_url?: string;
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

/**
 * Check API health
 */
export async function checkHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`);
  if (!response.ok) {
    throw new Error('API health check failed');
  }
  return response.json();
}

/**
 * Analyze an error log and get a fix
 */
export async function analyzeError(log: string, context?: string): Promise<AnalyzeResponse> {
  const response = await fetch(`${API_BASE_URL}/analyze`, {
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

export async function githubOAuthStart(): Promise<GithubOAuthStartResponse> {
  const response = await fetch(`${API_BASE_URL}/github/oauth/start`);
  if (!response.ok) {
    throw new Error('Failed to start GitHub OAuth');
  }
  return response.json();
}

export async function githubOAuthExchange(code: string): Promise<GithubOAuthExchangeResponse> {
  const response = await fetch(`${API_BASE_URL}/github/oauth/exchange`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ code }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'GitHub OAuth exchange failed');
  }
  return response.json();
}

export async function githubListRepos(sessionId: string): Promise<GithubRepoListResponse> {
  const response = await fetch(`${API_BASE_URL}/github/repos`, {
    headers: {
      'X-ROMA-GH-SESSION': sessionId,
    },
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to list repos');
  }
  return response.json();
}

export async function githubLogout(sessionId: string): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/github/logout`, {
    method: 'POST',
    headers: {
      'X-ROMA-GH-SESSION': sessionId,
    },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to disconnect GitHub');
  }
  return response.json();
}

export async function githubCloneRepo(
  repoUrl: string,
  sessionId: string,
  ref?: string,
): Promise<GithubCloneResponse> {
  const response = await fetch(`${API_BASE_URL}/github/clone`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ repo_url: repoUrl, session_id: sessionId, ref }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to clone repository');
  }
  return response.json();
}

export async function githubAnalyzeRepo(
  repoId: string,
  sessionId: string,
  log: string,
  language?: string,
): Promise<GithubAnalyzeResponse> {
  const response = await fetch(`${API_BASE_URL}/github/analyze`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-ROMA-GH-SESSION': sessionId,
    },
    body: JSON.stringify({ repo_id: repoId, log, language }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to analyze repo');
  }
  return response.json();
}

export async function githubApplyPatch(
  repoId: string,
  sessionId: string,
  filepath: string,
  content: string,
): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/github/apply`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-ROMA-GH-SESSION': sessionId,
    },
    body: JSON.stringify({ repo_id: repoId, filepath, content }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to apply patch');
  }
  return response.json();
}

export async function githubApplyPatchBatch(
  repoId: string,
  sessionId: string,
  patches: Array<{ filepath: string; content: string }>,
): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/github/apply-batch`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-ROMA-GH-SESSION': sessionId,
    },
    body: JSON.stringify({ repo_id: repoId, patches }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to apply patches');
  }
  return response.json();
}
export async function githubCommit(
  repoId: string,
  sessionId: string,
  branch: string,
  message: string,
): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/github/commit`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-ROMA-GH-SESSION': sessionId,
    },
    body: JSON.stringify({ repo_id: repoId, branch, message }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to commit changes');
  }
  return response.json();
}

export async function githubOpenPr(
  repoId: string,
  sessionId: string,
  branch: string,
  title: string,
  body?: string,
): Promise<GithubPrResponse> {
  const response = await fetch(`${API_BASE_URL}/github/pr`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-ROMA-GH-SESSION': sessionId,
    },
    body: JSON.stringify({ repo_id: repoId, branch, title, body }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to open PR');
  }
  return response.json();
}
