export interface SocialLink {
  label: string;
  url: string;
}

export interface ProfileInput {
  display_name: string;
  message: string;
  links: SocialLink[];
}

export interface Profile extends ProfileInput {
  tag: string;
  created_at: string;
  updated_at: string;
}

export interface TagAvailability {
  tag: string;
  available: boolean;
  reason: string | null;
}

export const MAX_LINKS = 20;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const BASE = import.meta.env.VITE_API_URL ?? "";

/** Turn a FastAPI error body (string detail or pydantic error list) into one readable line. */
export function errorMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string; loc?: unknown[] };
    const field = first.loc?.filter((p) => p !== "body").join(".");
    const msg = (first.msg ?? fallback).replace(/^Value error, /, "");
    return field ? `${field}: ${msg}` : msg;
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["X-Edit-Token"] = token;
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, errorMessage(body, `Request failed (${res.status})`));
  return body as T;
}

const enc = encodeURIComponent;

export const api = {
  getProfile: (tag: string) => request<Profile>(`/api/profiles/${enc(tag)}`),

  checkTag: (tag: string) => request<TagAvailability>(`/api/profiles/${enc(tag)}/available`),

  createProfile: (input: ProfileInput & { tag: string }) =>
    request<{ profile: Profile; edit_token: string }>("/api/profiles", {
      method: "POST",
      body: JSON.stringify(input),
    }),

  updateProfile: (tag: string, input: ProfileInput, token: string) =>
    request<Profile>(
      `/api/profiles/${enc(tag)}`,
      { method: "PUT", body: JSON.stringify(input) },
      token,
    ),

  deleteProfile: (tag: string, token: string) =>
    request<void>(`/api/profiles/${enc(tag)}`, { method: "DELETE" }, token),
};

export function isSafeUrl(url: string): boolean {
  try {
    const u = new URL(url);
    return (u.protocol === "http:" || u.protocol === "https:") && !!u.host;
  } catch {
    return false;
  }
}
