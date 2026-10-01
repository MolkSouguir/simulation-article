<script lang="ts">
	// Dropdown built on a popover, same pattern as DefaultSelectV2 in the Ageru
	// design system. `value` is bindable and `items` are { value, name } pairs.

	interface SelectItem {
		value: string;
		name: string;
	}

	interface Props {
		value?: string;
		items?: SelectItem[];
		label?: string;
		required?: boolean;
		placeholder?: string;
		disabled?: boolean;
		error?: string | null;
		wrapperClass?: string;
		class?: string;
		onchange?: (value: string) => void;
	}

	let {
		value = $bindable(""),
		items = [],
		label,
		required = false,
		placeholder = "Select...",
		disabled = false,
		error,
		wrapperClass = "mb-5",
		class: className = "",
		onchange,
	}: Props = $props();

	let isOpen = $state(false);
	let triggerRef: HTMLDivElement | undefined = $state();
	let popoverRef: HTMLDivElement | undefined = $state();
	let dropdownStyle = $state("");

	const selectedItem = $derived(items.find((item) => item.value === value));
	const displayText = $derived(selectedItem?.name ?? "");

	// Open below the field, or above it when there isn't enough room below.
	$effect(() => {
		if (!popoverRef) return;
		if (isOpen) {
			popoverRef.showPopover();
			requestAnimationFrame(() => {
				if (!triggerRef || !popoverRef) return;
				const triggerBox = triggerRef.getBoundingClientRect();
				const popoverHeight = popoverRef.getBoundingClientRect().height;
				const spaceBelow = window.innerHeight - triggerBox.bottom;
				const top = spaceBelow >= popoverHeight + 4 ? triggerBox.bottom + 4 : triggerBox.top - popoverHeight - 4;
				const left = Math.min(triggerBox.left, window.innerWidth - triggerBox.width - 8);
				dropdownStyle = `inset:unset;margin:0;top:${top}px;left:${left}px;width:${triggerBox.width}px;`;
			});
		} else {
			if (popoverRef.matches(":popover-open")) popoverRef.hidePopover();
		}
	});

	const toggle = () => {
		if (disabled) return;
		if (!isOpen && triggerRef) {
			const triggerBox = triggerRef.getBoundingClientRect();
			dropdownStyle = `inset:unset;margin:0;top:${triggerBox.bottom + 4}px;left:${triggerBox.left}px;width:${triggerBox.width}px;`;
		}
		isOpen = !isOpen;
	}

	const select = (item: SelectItem) => {
		if (disabled) return;
		const previousValue = value;
		value = item.value;
		isOpen = false;
		if (onchange && previousValue !== value) onchange(value);
	}

	const onClickOutside = (event: MouseEvent) => {
		const clickedNode = event.target as Node;
		if (!triggerRef?.contains(clickedNode) && !popoverRef?.contains(clickedNode)) isOpen = false;
	}

	const instanceId = crypto.randomUUID();
</script>

<svelte:window onclick={onClickOutside} />

<div class={wrapperClass}>
	{#if label}
		<label for="sel-{instanceId}" class="mb-1 flex text-sm font-medium text-tdefault">
			{label}
			{#if required}<span class="app-asterisk">*</span>{/if}
		</label>
	{/if}

	<!-- Trigger -->
	<div class="relative {className}" bind:this={triggerRef}>
		<input
			id="sel-{instanceId}"
			type="text"
			readonly
			{disabled}
			value={displayText}
			placeholder={placeholder}
			class="app-input pr-9 cursor-pointer {!selectedItem ? 'text-tdisabled' : ''} {isOpen ? 'border-brand' : ''}"
		/>
		<!-- Transparent button over the field so the whole field is clickable -->
		<button
			type="button"
			onclick={toggle}
			{disabled}
			class="absolute inset-0 w-full h-full bg-transparent border-0 cursor-pointer disabled:cursor-not-allowed"
			aria-label="Toggle dropdown"
		></button>
		<!-- Chevron -->
		<span
			class="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-tsubtle transition-transform {isOpen ? 'rotate-180' : ''}"
		>
			<svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
				<path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
			</svg>
		</span>
	</div>

	<!-- The list is a popover, so it shows on top of modal dialogs too -->
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div
		bind:this={popoverRef}
		popover="manual"
		style={dropdownStyle}
		class="z-50 bg-white border border-cbase rounded-lg shadow-lg max-h-60 overflow-y-auto p-0"
		ontoggle={(event: ToggleEvent) => { if (event.newState === "closed" && isOpen) isOpen = false; }}
	>
		{#if items.length > 0}
			{#each items as item}
				{@const isSelected = item.value === value}
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<div
					role="option"
					aria-selected={isSelected}
					onclick={() => select(item)}
					class="w-full px-4 py-2.5 text-sm cursor-pointer flex items-center gap-2
						{isSelected
							? 'bg-brand-light text-brand font-medium'
							: 'text-tdefault hover:bg-secondary-hover'}"
				>
					{#if isSelected}
						<svg class="h-3.5 w-3.5 shrink-0" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clip-rule="evenodd" />
						</svg>
					{:else}
						<span class="h-3.5 w-3.5 shrink-0"></span>
					{/if}
					{item.name}
				</div>
			{/each}
		{:else}
			<div class="px-4 py-3 text-sm text-tbody text-center">No options available</div>
		{/if}
	</div>

	{#if error}
		<p class="mt-1 text-sm text-danger">{error}</p>
	{/if}
</div>
