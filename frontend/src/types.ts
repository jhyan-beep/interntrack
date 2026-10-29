export const STATUSES = [
  "saved",
  "applied",
  "interview",
  "offer",
  "rejected",
  "withdrawn"
] as const;

export type ApplicationStatus = (typeof STATUSES)[number];

export interface InternshipApplication {
  id: number;
  company: string;
  role: string;
  status: ApplicationStatus;
  application_date: string;
  deadline: string | null;
  location: string | null;
  source_url: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApplicationInput {
  company: string;
  role: string;
  status: ApplicationStatus;
  application_date: string;
  deadline: string | null;
  location: string | null;
  source_url: string | null;
  notes: string | null;
}

export type AiDraftField = "company" | "role" | "location" | "deadline" | "source_url" | "notes";

export interface AiJobDraft {
  company: string | null;
  role: string | null;
  location: string | null;
  deadline: string | null;
  source_url: string | null;
  notes: string | null;
  uncertain_fields: AiDraftField[];
}

export interface ApplicationStats {
  total_applications: number;
  active_applications: number;
  by_status: Partial<Record<ApplicationStatus, number>>;
  upcoming_deadlines: Array<
    Pick<InternshipApplication, "id" | "company" | "role"> & { deadline: string }
  >;
}

export interface PaginatedApplications {
  items: InternshipApplication[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface User {
  id: number;
  email: string;
  email_verified: boolean;
  created_at: string;
}

export interface RuntimeInfo {
  mode: "web" | "desktop";
  ai_available: boolean;
  email_features_available: boolean;
}

export interface ReminderSettings {
  deadline_reminders_enabled: boolean;
  deadline_reminder_days: number;
  reminder_timezone: string;
}

export interface BetaProgress {
  application_count: number;
  email_verified: boolean;
  ai_import_used: boolean;
  reminders_enabled: boolean;
  feedback_submitted: boolean;
  activated: boolean;
}

export interface BetaFeedback {
  rating: number;
  comment: string | null;
  updated_at: string;
}

export type SortBy = "deadline" | "application_date" | "created_at" | "company";
export type SortOrder = "asc" | "desc";
