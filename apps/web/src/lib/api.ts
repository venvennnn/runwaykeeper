export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const DEMO_API_KEY =
  process.env.NEXT_PUBLIC_DEMO_KEY || "rk_demo_harbor_studio";

export async function fetchApi<T = any>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const headers = new Headers(options.headers || {});
  if (!headers.has("X-API-Key")) {
    headers.set("X-API-Key", DEMO_API_KEY);
  }
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      detail = parsed.detail || text;
    } catch {
      // noop
    }
    throw new Error(detail);
  }
  return res.json();
}

export function formatMoney(minor: number | null | undefined, currency = "USD"): string {
  if (minor === null || minor === undefined) return "—";
  const abs = Math.abs(minor);
  const sign = minor < 0 ? "-" : "";
  const dollars = (abs / 100).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${sign}$${dollars}`;
}
