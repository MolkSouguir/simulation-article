export const API_BASE = "http://localhost:8000/api";
const BASE = API_BASE;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
	const res = await fetch(`${BASE}${path}`, {
		cache: "no-store",
		headers: { "Content-Type": "application/json", ...init?.headers },
		...init,
	});
	if (!res.ok) {
		const text = await res.text();
		throw new Error(`${res.status} ${res.statusText}: ${text}`);
	}
	if (res.status === 204) return undefined as T;
	return res.json();
}

// Downloads a file the API sends as an attachment, under the name the API gives it
async function download(path: string, fallbackName: string): Promise<void> {
	const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
	if (!res.ok) {
		const text = await res.text();
		throw new Error(`${res.status} ${res.statusText}: ${text}`);
	}
	const disposition = res.headers.get("Content-Disposition") ?? "";
	const fileName = disposition.match(/filename="?([^";]+)"?/)?.[1] ?? fallbackName;
	const url = URL.createObjectURL(await res.blob());
	const link = document.createElement("a");
	link.href = url;
	link.download = fileName;
	link.click();
	URL.revokeObjectURL(url);
}

export const api = {
	get: <T>(path: string) => request<T>(path),
	download,
	post: <T>(path: string, body: unknown) =>
		request<T>(path, { method: "POST", body: JSON.stringify(body) }),
	patch: <T>(path: string, body: unknown) =>
		request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
	delete: (path: string) => request<void>(path, { method: "DELETE" }),
};
