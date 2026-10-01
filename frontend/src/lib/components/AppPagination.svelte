<script lang="ts">
	interface Props {
		total: number;       // total number of items
		page: number;        // current page (1-based), bindable
		pageSize?: number;   // items per page, bindable
		pageSizeOptions?: number[];
	}

	let {
		total,
		page = $bindable(1),
		pageSize = $bindable(20),
		pageSizeOptions = [10, 20, 50, 100],
	}: Props = $props();

	const totalPages = $derived(Math.max(1, Math.ceil(total / pageSize)));

	// Stay on a valid page when the list shrinks or the page size grows.
	$effect(() => {
		if (page > totalPages) page = totalPages;
	});

	const firstShown = $derived((page - 1) * pageSize + 1);
	const lastShown = $derived(Math.min(page * pageSize, total));

	// Page buttons: first, last, and the pages next to the current one, with "..." in the gaps.
	const pageNumbers = $derived((): (number | "...")[] => {
		if (totalPages <= 7) return Array.from({ length: totalPages }, (_, index) => index + 1);
		const pages: (number | "...")[] = [];
		const visiblePages = new Set(
			[1, totalPages, page - 1, page, page + 1].filter((pageNumber) => pageNumber >= 1 && pageNumber <= totalPages)
		);
		let previousPage: number | null = null;
		for (const pageNumber of [...visiblePages].sort((pageA, pageB) => pageA - pageB)) {
			if (previousPage !== null && pageNumber - previousPage > 1) pages.push("...");
			pages.push(pageNumber);
			previousPage = pageNumber;
		}
		return pages;
	});

	const goToPage = (pageNumber: number) => {
		if (pageNumber >= 1 && pageNumber <= totalPages) page = pageNumber;
	}

	const onPageSizeChange = (event: Event) => {
		pageSize = Number((event.target as HTMLSelectElement).value);
		page = 1;
	}
</script>

<div class="flex items-center justify-between text-sm text-tbody">
	<!-- Left: count + page size -->
	<div class="flex items-center gap-3">
		<span>{total === 0 ? "0" : `${firstShown}–${lastShown}`} of {total}</span>
		<div class="flex items-center gap-1.5">
			<span class="text-tsubtle">Rows</span>
			<select
				value={pageSize}
				onchange={onPageSizeChange}
				class="rounded-md border border-cbase bg-white px-2 py-1 text-sm text-tdefault
				       focus:outline-none focus:border-brand cursor-pointer"
			>
				{#each pageSizeOptions as sizeOption}
					<option value={sizeOption}>{sizeOption}</option>
				{/each}
			</select>
		</div>
	</div>

	<!-- Right: page controls -->
	<div class="flex items-center gap-1">
		<!-- Prev -->
		<button
			onclick={() => goToPage(page - 1)}
			disabled={page === 1}
			class="flex h-8 w-8 items-center justify-center rounded-md border border-cbase text-tsubtle
			       hover:bg-secondary hover:text-tdefault disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
			aria-label="Previous page"
		>
			<svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
				<path fill-rule="evenodd" d="M12.79 5.23a.75.75 0 01-.02 1.06L8.832 10l3.938 3.71a.75.75 0 11-1.04 1.08l-4.5-4.25a.75.75 0 010-1.08l4.5-4.25a.75.75 0 011.06.02z" clip-rule="evenodd"/>
			</svg>
		</button>

		<!-- Page numbers -->
		{#each pageNumbers() as pageEntry}
			{#if pageEntry === "..."}
				<span class="flex h-8 w-8 items-center justify-center text-tsubtle select-none">…</span>
			{:else}
				<button
					onclick={() => goToPage(pageEntry)}
					class="flex h-8 w-8 items-center justify-center rounded-md border text-sm transition-colors
					       {page === pageEntry
					           ? 'border-brand bg-brand text-white font-medium'
					           : 'border-cbase hover:bg-secondary text-tdefault'}"
				>
					{pageEntry}
				</button>
			{/if}
		{/each}

		<!-- Next -->
		<button
			onclick={() => goToPage(page + 1)}
			disabled={page === totalPages}
			class="flex h-8 w-8 items-center justify-center rounded-md border border-cbase text-tsubtle
			       hover:bg-secondary hover:text-tdefault disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
			aria-label="Next page"
		>
			<svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
				<path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd"/>
			</svg>
		</button>
	</div>
</div>
