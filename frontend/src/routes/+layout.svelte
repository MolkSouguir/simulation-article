<script lang="ts">
	import favicon from '$lib/assets/favicon.svg';
	import gmeca from '$lib/assets/gmeca.jpeg';
	import chwapi from '$lib/assets/chwapi.jpeg';
	import "../app.css";
	import { page } from "$app/state";

	const navItems = [
		{ href: "/machines", label: "Machines" },
		{ href: "/spare_parts", label: "Spare Parts" },
		{ href: "/cost_profiles", label: "Costs" },
		{ href: "/preventive_maintenance", label: "PM schedules" },
		{ href: "/scenarios", label: "Scenarios" },
		{ href: "/simulation", label: "Simulation" },
		{ href: "/history", label: "History" },
		{ href: "/tools", label: "Tools" },
	];

	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<div class="flex h-screen bg-background">
	<aside class="w-56 border-r border-border bg-card flex flex-col">
		<div class="px-4 py-5 border-b border-border flex flex-col items-center gap-3">
			<img src={gmeca} alt="GMECA Polytech Mons" class="w-full object-contain max-h-14" />
			<img src={chwapi} alt="CHwapi" class="w-full object-contain max-h-14" />
		</div>
		<div class="px-4 py-3 border-b border-border">
			<h1 class="font-semibold text-sm tracking-tight">SimulationApp</h1>
			<p class="text-xs text-muted-foreground mt-0.5">Fleet Management</p>
		</div>
		<nav class="flex-1 px-2 py-3 space-y-0.5">
			{#each navItems as item}
				<a
					href={item.href}
					class="flex items-center px-3 py-2 text-sm rounded-md transition-colors
						{page.url.pathname.startsWith(item.href)
						? 'bg-accent text-accent-foreground font-medium'
						: 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'}"
				>
					{item.label}
				</a>
			{/each}
		</nav>
	</aside>

	<main class="flex-1 overflow-auto">
		{@render children()}
	</main>
</div>
