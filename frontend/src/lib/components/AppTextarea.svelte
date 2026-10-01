<script lang="ts">
	import type { HTMLTextareaAttributes } from "svelte/elements";

	interface Props extends HTMLTextareaAttributes {
		value?: string;
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
		rows = 4,
		...rest
	}: Props = $props();

	const inputId = id ?? crypto.randomUUID();
</script>

<div class={wrapperClass}>
	{#if label}
		<label for={inputId} class="mb-1 flex text-sm font-medium text-tdefault">
			{label}
			{#if required}<span class="app-asterisk">*</span>{/if}
		</label>
	{/if}

	<textarea
		id={inputId}
		class="app-input resize-y {className}"
		bind:value
		{required}
		{rows}
		{...rest}
	></textarea>

	{#if error}
		<p class="mt-1 text-sm text-danger">{error}</p>
	{/if}
</div>
