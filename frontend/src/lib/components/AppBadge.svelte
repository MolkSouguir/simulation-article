<script lang="ts">
	import type { Snippet } from "svelte";

	type Variant = "default" | "brand" | "success" | "danger" | "warning" | "secondary";

	interface Props {
		variant?: Variant;
		class?: string;
		children?: Snippet;
	}

	let { variant = "default", class: className = "", children }: Props = $props();

	const variantClass: Record<Variant, string> = {
		default:   "bg-gray-100 text-tdefault border-gray-200",
		brand:     "bg-brand-light text-brand border-brand-focus",
		success:   "bg-green-50 text-success border-green-200",
		danger:    "bg-red-50 text-danger border-red-200",
		warning:   "bg-orange-50 text-warning border-orange-200",
		secondary: "bg-secondary text-tbody border-cbase",
	};
</script>

<span class="inline-flex items-center px-2.5 py-0.5 text-xs font-semibold rounded border {variantClass[variant]} {className}">
	{@render children?.()}
</span>
