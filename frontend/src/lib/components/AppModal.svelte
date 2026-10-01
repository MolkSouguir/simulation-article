<script lang="ts">
	// Modal built on the native <dialog>. Bind `open` to show or hide it.
	// Clicking outside only closes it when closeOnBackdrop is set.
	import type { Snippet } from "svelte";

	type Size = "sm" | "md" | "lg" | "xl" | "2xl" | "screen";

	interface Props {
		open?: boolean;
		title?: string;
		size?: Size;
		showClose?: boolean;
		closeOnBackdrop?: boolean;
		children?: Snippet;
		footer?: Snippet;
		class?: string;
	}

	let {
		open = $bindable(false),
		title,
		size = "md",
		showClose = true,
		closeOnBackdrop = false,
		children,
		footer,
		class: className = "",
	}: Props = $props();

	const sizeClass: Record<Size, string> = {
		sm:  "max-w-sm",
		md:  "max-w-md",
		lg:  "max-w-lg",
		xl:  "max-w-xl",
		"2xl": "max-w-2xl",
		screen: "max-w-none",
	};

	let dialogEl: HTMLDialogElement | undefined = $state();

	$effect(() => {
		if (!dialogEl) return;
		if (open) {
			if (!dialogEl.open) dialogEl.showModal();
		} else {
			if (dialogEl.open) dialogEl.close();
		}
	});

	const onDialogClose = () => { open = false; };

	// A click on the <dialog> element itself (not its content) is a click on the backdrop.
	const onDialogClick = (event: MouseEvent) => {
		if (closeOnBackdrop && (event.target as HTMLElement) === dialogEl) open = false;
	};
</script>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_noninteractive_element_interactions -->
<dialog
	bind:this={dialogEl}
	onclose={onDialogClose}
	onclick={onDialogClick}
	style={size === "screen" ? "width:90vw;height:90vh;" : ""}
	class="m-auto w-full {sizeClass[size]} rounded-xl bg-white shadow-xl p-0
	       backdrop:bg-tdefault/40 open:flex open:flex-col
	       focus:outline-none {className}"
>
	<!-- Header -->
	{#if title || showClose}
		<div class="flex items-center justify-between border-b border-cbase px-6 py-4">
			{#if title}
				<h3 class="text-base font-semibold text-theading">{title}</h3>
			{:else}
				<span></span>
			{/if}
			{#if showClose}
				<button
					type="button"
					onclick={() => (open = false)}
					class="rounded-md p-1 text-tsubtle hover:bg-secondary-hover hover:text-tdefault transition-colors focus:outline-none"
					aria-label="Close"
				>
					<svg class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
						<path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
					</svg>
				</button>
			{/if}
		</div>
	{/if}

	<!-- Body -->
	<div class="flex-1 overflow-y-auto px-6 py-5">
		{@render children?.()}
	</div>

	<!-- Footer -->
	{#if footer}
		<div class="flex items-center justify-end gap-2 border-t border-cbase px-6 py-4">
			{@render footer()}
		</div>
	{/if}
</dialog>
