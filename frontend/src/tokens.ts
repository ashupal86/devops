// Edit tokens are kept per-browser so the owner can come back and edit without logging in.
const key = (tag: string) => `social-links:token:${tag.toLowerCase()}`;

export function saveToken(tag: string, token: string): void {
  try {
    localStorage.setItem(key(tag), token);
  } catch {
    /* storage unavailable (private mode); the user still has the key on screen */
  }
}

export function loadToken(tag: string): string | null {
  try {
    return localStorage.getItem(key(tag));
  } catch {
    return null;
  }
}

export function clearToken(tag: string): void {
  try {
    localStorage.removeItem(key(tag));
  } catch {
    /* ignore */
  }
}
