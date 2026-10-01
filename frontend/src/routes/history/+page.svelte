<script lang="ts">
	import { goto } from "$app/navigation";
	import { simulationRunsApi, type SimulationRunSummary } from "$lib/api/index.js";
	import { AppButton, AppInput, AppModal, AppDataGrid } from "$lib/components/index.js";
	import type { Column } from "$lib/components/types.js";
	import { fmtDateTime } from "$lib/utils/format.js";

	let runs = $state<SimulationRunSummary[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let modalOpen = $state(false);
	let editing = $state<SimulationRunSummary | null>(null);
	let runName = $state("");
	let saving = $state(false);

	const METHOD_LABELS: Record<string, string> = {
		AHP: "AHP",
		TOPSIS: "TOPSIS",
		ELECTRE2: "ELECTRE II",
	};

	const load = async () => {
		loading = true; error = null;
		try { runs = await simulationRunsApi.list(); }
		catch (loadError) { error = String(loadError); }
		finally { loading = false; }
	};

	const open = (run: SimulationRunSummary) => goto(`/simulation?run=${run.id}`);

	// Id of the run whose PDF is being built (it takes a few seconds)
	let exportingId = $state<string | null>(null);
	const exportPdf = async (run: SimulationRunSummary) => {
		exportingId = run.id;
		try { await simulationRunsApi.downloadPdf(run.id); }
		catch (exportError) { alert(String(exportError)); }
		finally { exportingId = null; }
	};

	const openRename = (run: SimulationRunSummary) => { editing = run; runName = run.name; modalOpen = true; };

	const saveName = async () => {
		if (!editing) return;
		saving = true;
		try {
			const updated = await simulationRunsApi.update(editing.id, { name: runName.trim() });
			runs = runs.map((run) => run.id === editing!.id ? updated : run);
			modalOpen = false;
		} catch (saveError) { alert(String(saveError)); }
		finally { saving = false; }
	};

	const remove = async (run: SimulationRunSummary) => {
		if (!confirm(`Delete run "${run.name}" from ${fmtDateTime(run.created_at)}?`)) return;
		try {
			await simulationRunsApi.delete(run.id);
			runs = runs.filter((other) => other.id !== run.id);
		} catch (deleteError) { alert(String(deleteError)); }
	};

	// Filter choices come from the runs that exist
	const methodFilterItems = $derived(
		[...new Set(runs.map((run) => run.method))].map((method) => ({ value: method, name: METHOD_LABELS[method] ?? method }))
	);
	const machineTypeFilterItems = $derived(
		[...new Set(runs.map((run) => run.machine_type))].map((machineType) => ({ value: machineType, name: machineType }))
	);

	const columns: Column<SimulationRunSummary>[] = $derived([
		{ key: "name",              header: "Name",             cellClass: "font-medium text-tdefault" },
		{ key: "created_at",        header: "Date",             render: (run) => fmtDateTime(run.created_at), filterable: false },
		{ key: "method",            header: "Method",           render: (run) => METHOD_LABELS[run.method] ?? run.method, filterItems: methodFilterItems },
		{ key: "machine_type",      header: "Machine type",     filterItems: machineTypeFilterItems },
		{ key: "alternative_count", header: "Alternatives",     align: "right", filterable: false },
		{ key: "best_alternative",  header: "Ranked 1st",       render: (run) => run.best_alternative ?? "—" },
		{ key: "simulation_number", header: "MC runs",          align: "right", filterable: false },
		{ key: "period",            header: "Horizon",          render: (run) => `${run.period} yrs`, align: "right", filterable: false },
		{ key: "seed",              header: "Seed",             align: "right", filterable: false },
	]);

	load();
</script>

<div class="p-6 space-y-4">
	<div class="flex items-center justify-between">
		<div>
			<h2 class="text-xl font-semibold text-theading">Simulation History</h2>
			<p class="text-sm text-tbody">Past simulation runs — open one to see its results again</p>
		</div>
		<AppButton onclick={() => goto("/simulation")}>New Simulation</AppButton>
	</div>

	<AppDataGrid
		data={runs}
		{columns}
		{loading}
		{error}
		searchPlaceholder="Search runs..."
		emptyMessage="No simulation runs yet. Runs are saved here automatically."
		actions={runActions}
	/>
</div>

{#snippet runActions(run: SimulationRunSummary)}
	<div class="flex gap-1.5">
		<AppButton size="sm" onclick={() => open(run)}>Open</AppButton>
		<AppButton variant="secondary" size="sm" onclick={() => exportPdf(run)} loading={exportingId === run.id}>PDF</AppButton>
		<AppButton variant="secondary" size="sm" onclick={() => openRename(run)}>Rename</AppButton>
		<AppButton variant="danger-secondary" size="sm" onclick={() => remove(run)}>Delete</AppButton>
	</div>
{/snippet}

<AppModal bind:open={modalOpen} title="Rename Run" size="md">
	<AppInput label="Name" bind:value={runName} placeholder="e.g. Ventilators — 5 criteria, revision 1" required />
	{#snippet footer()}
		<AppButton onclick={saveName} loading={saving} disabled={!runName.trim()}>Save</AppButton>
		<AppButton variant="secondary" onclick={() => (modalOpen = false)}>Cancel</AppButton>
	{/snippet}
</AppModal>
