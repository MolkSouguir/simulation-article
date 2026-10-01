<script lang="ts">
	import type { Snippet } from "svelte";
	import type { Column } from "./types.js";
	import AppPagination from "./AppPagination.svelte";
	import AppInput from "./AppInput.svelte";
	import AppSelect from "./AppSelect.svelte";
	import AppCheckbox from "./AppCheckbox.svelte";

	interface Props {
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		data: any[];
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		columns: Column<any>[];
		loading?: boolean;
		error?: string | null;
		emptyMessage?: string;
		selectable?: boolean;
		selectedIds?: Set<string>;
		idKey?: string;
		searchPlaceholder?: string;
		toolbar?: Snippet;
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		actions?: Snippet<[any]>;
	}

	let {
		data,
		columns,
		loading = false,
		error = null,
		emptyMessage = "No records found.",
		selectable = false,
		selectedIds = $bindable(new Set<string>()),
		idKey = "id",
		searchPlaceholder = "Search...",
		toolbar,
		actions,
	}: Props = $props();

	let search = $state("");

	const asRecord = (row: unknown) => row as Record<string, unknown>;

	let columnFilters = $state<Record<string, string>>({});
	let sortKey = $state<string | null>(null);
	let sortDir = $state<"asc" | "desc">("asc");
	let page = $state(1);
	let pageSize = $state(20);

	const toggleSort = (key: string) => {
		if (sortKey === key) {
			sortDir = sortDir === "asc" ? "desc" : "asc";
		} else {
			sortKey = key;
			sortDir = "asc";
		}
		page = 1;
	};

	const searched = $derived.by(() => {
		if (!search.trim()) return data;
		const lower = search.toLowerCase();
		return data.filter((row) =>
			Object.values(asRecord(row)).some((value) => String(value ?? "").toLowerCase().includes(lower))
		);
	});

	const filtered = $derived.by(() => {
		let rows = searched;
		for (const [key, filterText] of Object.entries(columnFilters)) {
			if (!filterText) continue;
			const lower = filterText.toLowerCase();
			rows = rows.filter((row) => String(asRecord(row)[key] ?? "").toLowerCase().includes(lower));
		}
		return rows;
	});

	// Numbers sort numerically, everything else as text (with "2" before "10").
	const sorted = $derived.by(() => {
		if (!sortKey) return filtered;
		const key = sortKey;
		return [...filtered].sort((rowA, rowB) => {
			const valueA = asRecord(rowA)[key] ?? "";
			const valueB = asRecord(rowB)[key] ?? "";
			const numberA = Number(valueA);
			const numberB = Number(valueB);
			const comparison = (!isNaN(numberA) && !isNaN(numberB))
				? numberA - numberB
				: String(valueA).localeCompare(String(valueB), undefined, { numeric: true, sensitivity: "base" });
			return sortDir === "asc" ? comparison : -comparison;
		});
	});

	const paginated = $derived(sorted.slice((page - 1) * pageSize, page * pageSize));

	const pageIds = $derived(paginated.map((row) => String(asRecord(row)[idKey])));
	const allPageSelected = $derived(pageIds.length > 0 && pageIds.every((id) => selectedIds.has(id)));
	const somePageSelected = $derived(pageIds.some((id) => selectedIds.has(id)));

	const toggleAll = () => {
		const next = new Set(selectedIds);
		if (allPageSelected) {
			pageIds.forEach((id) => next.delete(id));
		} else {
			pageIds.forEach((id) => next.add(id));
		}
		selectedIds = next;
	};

	const toggleRow = (id: string) => {
		const next = new Set(selectedIds);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		selectedIds = next;
	};

	// Go back to page 1 whenever the search or a column filter changes.
	$effect(() => {
		Object.values(columnFilters);
		search;
		page = 1;
	});

	const columnCount = $derived(columns.length + (selectable ? 1 : 0) + (actions ? 1 : 0));
</script>

<div class="space-y-3">
	<div class="flex items-center justify-end gap-2">
		{#if toolbar}
			{@render toolbar()}
		{/if}
		<AppInput
			bind:value={search}
			placeholder={searchPlaceholder}
			wrapperClass="mb-0 max-w-xs"
		/>
	</div>

	{#if loading}
		<p class="text-sm text-tbody">Loading...</p>
	{:else if error}
		<p class="text-sm text-danger">{error}</p>
	{:else}
		<div class="rounded-lg border border-cbase overflow-hidden">
			<table class="w-full text-sm">
				<thead class="bg-secondary border-b border-cbase">
					<tr>
						{#if selectable}
							<th class="px-3 py-3 w-10">
								<AppCheckbox
									checked={allPageSelected}
									indeterminate={somePageSelected && !allPageSelected}
									onchange={toggleAll}
									wrapperClass=""
								/>
							</th>
						{/if}
						{#each columns as column}
							<th
								class="px-4 py-2 text-left font-medium text-tsubtle {column.sortable !== false ? 'cursor-pointer select-none hover:text-tdefault' : ''}"
								onclick={column.sortable !== false ? () => toggleSort(column.key) : undefined}
							>
								<div class="flex items-center gap-1">
									<span>{column.header}</span>
									{#if column.sortable !== false && sortKey === column.key}
										<span class="text-xs">{sortDir === "asc" ? "↑" : "↓"}</span>
									{/if}
								</div>
								{#if column.filterable !== false}
									<div role="none" onclick={(event) => event.stopPropagation()} class="mt-1">
										{#if column.filterItems}
											<AppSelect
												items={[{ value: "", name: "All" }, ...column.filterItems]}
												value={columnFilters[column.key] ?? ""}
												onchange={(selected) => { columnFilters = { ...columnFilters, [column.key]: selected }; }}
												wrapperClass=""
											/>
										{:else}
											<AppInput
												placeholder="Filter…"
												value={columnFilters[column.key] ?? ""}
												oninput={(event) => { columnFilters = { ...columnFilters, [column.key]: (event.currentTarget as HTMLInputElement).value }; }}
												wrapperClass=""
											/>
										{/if}
									</div>
								{/if}
							</th>
						{/each}
						{#if actions}
							<th class="px-4 py-3"></th>
						{/if}
					</tr>
				</thead>
				<tbody class="divide-y divide-cbase">
					{#each paginated as row}
						{@const rowId = String(asRecord(row)[idKey])}
						{@const selected = selectedIds.has(rowId)}
						<tr class="transition-colors hover:bg-secondary {selected ? 'bg-brand/5' : ''}">
							{#if selectable}
								<td class="px-3 py-3">
									<AppCheckbox
										checked={selected}
										onchange={() => toggleRow(rowId)}
										wrapperClass=""
									/>
								</td>
							{/if}
							{#each columns as column}
								<td class="px-4 py-3 text-tbody {column.cellClass ?? ''} {column.align === 'right' ? 'text-right' : ''}">
									{#if column.render}
										{column.render(row)}
									{:else}
										{asRecord(row)[column.key] ?? ""}
									{/if}
								</td>
							{/each}
							{#if actions}
								<td class="px-4 py-3">
									{@render actions(row)}
								</td>
							{/if}
						</tr>
					{:else}
						<tr>
							<td colspan={columnCount} class="px-4 py-10 text-center text-tbody">{emptyMessage}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<AppPagination total={filtered.length} bind:page bind:pageSize />
	{/if}
</div>
