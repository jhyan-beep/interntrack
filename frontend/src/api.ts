import type {
  ApplicationInput,
  ApplicationStats,
  ApplicationStatus,
  InternshipApplication,
  SortBy,
  SortOrder
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

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function getApplications(filters: {
  company?: string;
  status?: ApplicationStatus | "all";
  sortBy: SortBy;
  sortOrder: SortOrder;
}): Promise<InternshipApplication[]> {
  const params = new URLSearchParams({
    sort_by: filters.sortBy,
    sort_order: filters.sortOrder
  });
  if (filters.company) params.set("company", filters.company);
  if (filters.status && filters.status !== "all") params.set("status", filters.status);
  return request(`/applications?${params.toString()}`);
}

export function getStats(): Promise<ApplicationStats> {
  return request("/stats");
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
  const response = await fetch(`${API_BASE_URL}/applications/export.csv`);
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

