// Number and date formatting shared by the pages.

/** Number with a fixed number of decimals, or "—" when there is no value. */
export const fmtNum = (value: number | null, decimals = 4): string => {
	if (value == null) return "—";
	return value.toFixed(decimals);
};

/** Table cell: small numbers with 4 decimals, large ones rounded with thousands separators. */
export const fmtCell = (value: unknown): string => {
	if (typeof value === "number")
		return Math.abs(value) < 10 ? value.toFixed(4) : Math.round(value).toLocaleString();
	return String(value ?? "");
};

/** Fraction (0 to 1) shown as a percentage, with three decimals by default. */
export const pct = (fraction: number, decimals = 3): string => (fraction * 100).toFixed(decimals) + "%";

/** Amount in euros, rounded. */
export const eur = (amount: number): string => "€" + Math.round(amount).toLocaleString();

/** ISO date as local date and time, e.g. "23 Sep 2026, 14:05". */
export const fmtDateTime = (iso: string): string =>
	new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
