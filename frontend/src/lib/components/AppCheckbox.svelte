<script lang="ts">
	interface Props {
		checked?: boolean;
		indeterminate?: boolean;
		label?: string;
		disabled?: boolean;
		error?: string | null;
		wrapperClass?: string;
		class?: string;
		onchange?: (checked: boolean) => void;
	}

	let {
		checked = $bindable(false),
		indeterminate = false,
		label,
		disabled = false,
		error,
		wrapperClass = "mb-5",
		class: className = "",
		onchange,
	}: Props = $props();

	let inputEl = $state<HTMLInputElement | undefined>();

	$effect(() => {
		if (inputEl) inputEl.indeterminate = indeterminate;
	});

	const inputId = crypto.randomUUID();
</script>

<div class={wrapperClass}>
	<label for={inputId} class="flex items-center gap-2.5 cursor-pointer {disabled ? 'cursor-not-allowed opacity-60' : ''}">
		<input
			id={inputId}
			type="checkbox"
			bind:checked
			bind:this={inputEl}
			{disabled}
			onchange={() => onchange?.(checked)}
			class="h-4 w-4 rounded border-cbase text-brand accent-brand focus:ring-0 focus:outline-none {className}"
		/>
		{#if label}
			<span class="text-sm font-medium text-tdefault">{label}</span>
		{/if}
	</label>
	{#if error}
		<p class="mt-1 text-sm text-danger">{error}</p>
	{/if}
</div>
