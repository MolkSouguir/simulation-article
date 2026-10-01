<script lang="ts">
	// Dropdown for picking a related record (a cost profile, a PM schedule, ...).
	// The options come from `loadItems()`, and values are record IDs as strings.
	// With `nullable`, a "— None —" entry is added and clearing it sends null to onchange.
	import AppSelect from "./AppSelect.svelte";

	interface SelectItem { value: string; name: string; }

	interface Props {
		value?: string;
		loadItems: () => Promise<SelectItem[]>;
		nullable?: boolean;
		label?: string;
		required?: boolean;
		placeholder?: string;
		disabled?: boolean;
		error?: string | null;
		wrapperClass?: string;
		class?: string;
		onchange?: (value: string | null) => void;
	}

	let {
		value = $bindable(""),
		loadItems,
		nullable = false,
		label,
		required = false,
		placeholder = "Select...",
		disabled = false,
		error,
		wrapperClass = "mb-5",
		class: className = "",
		onchange,
	}: Props = $props();

	let rawItems = $state<SelectItem[]>([]);
	let fetching = $state(true);
	let fetchError = $state<string | null>(null);

	$effect(() => {
		fetching = true;
		fetchError = null;
		loadItems()
			.then((result) => { rawItems = result; })
			.catch((loadError) => { fetchError = String(loadError); })
			.finally(() => { fetching = false; });
	});

	const items = $derived(
		nullable
			? [{ value: "", name: "— None —" }, ...rawItems]
			: rawItems
	);

	const handleChange = (selectedValue: string) => {
		onchange?.(selectedValue === "" ? null : selectedValue);
	}
</script>

<AppSelect
	bind:value
	{items}
	{label}
	{required}
	placeholder={fetching ? "Loading..." : placeholder}
	disabled={disabled || fetching}
	error={error ?? fetchError}
	{wrapperClass}
	class={className}
	onchange={handleChange}
/>
