/**
 * Shared component types.
 * Import from here rather than from individual component files.
 */

export interface FilterItem {
	value: string;
	name: string;
}

export interface Column<TData> {
	key: string;
	header: string;
	render?: (row: TData) => string;
	/** Omit to disable filtering on this column. Provide filterItems to use a select. */
	filterable?: boolean;
	filterItems?: FilterItem[];   // if set, renders AppSelect instead of AppInput
	sortable?: boolean;
	align?: "left" | "right";
	cellClass?: string;
}
