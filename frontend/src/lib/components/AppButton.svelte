<script lang="ts">
	import type { HTMLButtonAttributes } from "svelte/elements";

	type Variant =
		| "brand"
		| "brand-secondary"
		| "secondary"
		| "danger"
		| "danger-secondary"
		| "success";

	type Size = "xs" | "sm" | "md" | "lg" | "xl";

	interface Props extends HTMLButtonAttributes {
		variant?: Variant;
		size?: Size;
		loading?: boolean;
		class?: string;
	}

	let {
		variant = "brand",
		size = "md",
		loading = false,
		disabled,
		class: className = "",
		children,
		...rest
	}: Props = $props();

	const variantClass: Record<Variant, string> = {
		"brand":           "app-btn-brand",
		"brand-secondary": "app-btn-brand-sec",
		"secondary":       "app-btn-secondary",
		"danger":          "app-btn-danger",
		"danger-secondary":"app-btn-danger-sec",
		"success":         "app-btn-success",
	};

	const sizeClass: Record<Size, string> = {
		xs: "app-btn-xs",
		sm: "app-btn-sm",
		md: "app-btn-md",
		lg: "app-btn-lg",
		xl: "app-btn-xl",
	};

	const isDisabled = $derived(disabled || loading);
</script>

<button
	class="app-btn {variantClass[variant]} {sizeClass[size]} {className}"
	disabled={isDisabled}
	{...rest}
>
	{#if loading}
		<svg class="animate-spin -ml-0.5 mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24">
			<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
			<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
		</svg>
	{/if}
	{@render children?.()}
</button>
