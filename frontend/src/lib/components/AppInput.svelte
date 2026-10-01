<script lang="ts">
	import type { HTMLInputAttributes } from "svelte/elements";

	interface Props extends Omit<HTMLInputAttributes, "value"> {
		value?: string | number | null;
		label?: string;
		required?: boolean;
		error?: string | null;
		wrapperClass?: string;
	}

	let {
		value = $bindable(""),
		label,
		required = false,
		error,
		wrapperClass = "mb-5",
		class: className = "",
		id,
		...rest
	}: Props = $props();

	const inputId = $derived(id ?? crypto.randomUUID());
</script>

<div class={wrapperClass}>
	{#if label}
		<label for={inputId} class="mb-1 flex text-sm font-medium text-tdefault">
			{label}
			{#if required}<span class="app-asterisk">*</span>{/if}
		</label>
	{/if}

	<input
		id={inputId}
		class="app-input {className}"
		bind:value
		{required}
		{...rest}
	/>

	{#if error}
		<p class="mt-1 text-sm text-danger">{error}</p>
	{/if}
</div>
