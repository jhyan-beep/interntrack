import type {
  ApplicationInput,
  ApplicationStats,
  ApplicationStatus,
  AiJobDraft,
  BetaFeedback,
  BetaProgress,
  InternshipApplication,
  PaginatedApplications,
  ReminderSettings,
  RuntimeInfo,
  SortBy,
  SortOrder,
  User
} from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers
    }
  });

  if (!response.ok) {
    let message = "Something went wrong. Please try again.";
    try {
      const body = await response.json();
      if (typeof body.detail === "string") {
        message = body.detail;
      } else if (Array.isArray(body.detail)) {
        message = body.detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join(". ");
      }
    } catch {
      // Keep the friendly fallback when the server does not return JSON.
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204 || response.headers.get("Content-Length") === "0") {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export function getApplications(filters: {
  company?: string;
  status?: ApplicationStatus | "all";
  sortBy: SortBy;
  sortOrder: SortOrder;
  page?: number;
  pageSize?: number;
}): Promise<PaginatedApplications> {
  const params = new URLSearchParams({
    sort_by: filters.sortBy,
    sort_order: filters.sortOrder
  });
  params.set("page", String(filters.page ?? 1));
  params.set("page_size", String(filters.pageSize ?? 20));
  if (filters.company) params.set("company", filters.company);
  if (filters.status && filters.status !== "all") params.set("status", filters.status);
  return request(`/applications?${params.toString()}`);
}

export function getStats(): Promise<ApplicationStats> {
  return request("/stats");
}

export function getCurrentUser(): Promise<User> {
  return request("/auth/me");
}

export function getRuntimeInfo(): Promise<RuntimeInfo> {
  return request("/runtime");
}

export function recordBetaSession(): Promise<void> {
  return request("/beta/session", { method: "POST" });
}

export function getBetaProgress(): Promise<BetaProgress> {
  return request("/beta/progress");
}

export function submitBetaFeedback(rating: number, comment: string): Promise<BetaFeedback> {
  return request("/beta/feedback", {
    method: "PUT",
    body: JSON.stringify({ rating, comment: comment || null })
  });
}

export function register(email: string, password: string): Promise<User> {
  return request("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password })
  });
}

export function login(email: string, password: string): Promise<User> {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password })
  });
}

export function logout(): Promise<void> {
  return request("/auth/logout", { method: "POST" });
}

export function deleteAccount(password: string): Promise<void> {
  return request("/auth/me", {
    method: "DELETE",
    body: JSON.stringify({ password })
  });
}

export function requestEmailVerification(): Promise<void> {
  return request("/auth/email/verification/request", { method: "POST" });
}

export function getReminderSettings(): Promise<ReminderSettings> {
  return request("/reminders/settings");
}

export function updateReminderSettings(
  settings: ReminderSettings
): Promise<ReminderSettings> {
  return request("/reminders/settings", {
    method: "PATCH",
    body: JSON.stringify(settings)
  });
}

export function verifyEmail(token: string): Promise<User> {
  return request("/auth/email/verify", {
    method: "POST",
    body: JSON.stringify({ token })
  });
}

export function forgotPassword(email: string): Promise<void> {
  return request("/auth/password/forgot", {
    method: "POST",
    body: JSON.stringify({ email })
  });
}

export function resetPassword(token: string, newPassword: string): Promise<void> {
  return request("/auth/password/reset", {
    method: "POST",
    body: JSON.stringify({ token, new_password: newPassword })
  });
}

export function parseJobPosting(jobText: string, sourceUrl: string): Promise<AiJobDraft> {
  return request("/ai/job-draft", {
    method: "POST",
    body: JSON.stringify({
      job_text: jobText,
      source_url: sourceUrl || null
    })
  });
}

export function createApplication(input: ApplicationInput): Promise<InternshipApplication> {
  return request("/applications", { method: "POST", body: JSON.stringify(input) });
}

export function updateApplication(
  id: number,
  input: Partial<ApplicationInput>
): Promise<InternshipApplication> {
  return request(`/applications/${id}`, { method: "PATCH", body: JSON.stringify(input) });
}

export function deleteApplication(id: number): Promise<void> {
  return request(`/applications/${id}`, { method: "DELETE" });
}

export async function downloadCsv(): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/applications/export.csv`, {
    credentials: "include"
  });
  if (!response.ok) throw new ApiError("Could not export applications.", response.status);

  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = disposition.match(/filename="?([^";]+)"?/)?.[1] ?? "applications.csv";
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
