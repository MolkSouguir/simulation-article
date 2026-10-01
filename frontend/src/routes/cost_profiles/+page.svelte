<script lang="ts">
	import { costProfilesApi, type MaintenanceCostData, type MaintenanceCostDataCreate } from "$lib/api/index.js";
	import { AppButton, AppInput, AppModal, AppDataGrid } from "$lib/components/index.js";
	import type { Column } from "$lib/components/types.js";

	let costs = $state<MaintenanceCostData[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let modalOpen = $state(false);
	let editing = $state<MaintenanceCostData | null>(null);
	let saving = $state(false);

	const emptyForm = (): MaintenanceCostDataCreate => ({
		name: "",
		hourly_labor_cost: 0,
		corrective_maintenance_hours: 0,
		corrective_maintenance_additional_downtime_hours: 0,
		preventive_maintenance_hours: 0,
	});

	let form = $state<MaintenanceCostDataCreate>(emptyForm());

	const load = async () => {
		loading = true; error = null;
		try { costs = await costProfilesApi.list(); }
		catch (loadError) { error = String(loadError); }
		finally { loading = false; }
	};

	const openCreate = () => { editing = null; form = emptyForm(); modalOpen = true; };
	const openEdit = (cost: MaintenanceCostData) => { editing = cost; form = { ...cost }; modalOpen = true; };

	const save = async () => {
		saving = true;
		try {
			if (editing) {
				const updated = await costProfilesApi.update(editing.id, form);
				costs = costs.map((cost) => cost.id === editing!.id ? updated : cost);
			} else {
				const created = await costProfilesApi.create(form);
				costs = [...costs, created];
			}
			modalOpen = false;
		} catch (saveError) { alert(String(saveError)); }
		finally { saving = false; }
	};

	const remove = async (cost: MaintenanceCostData) => {
		if (!confirm(`Delete cost "${cost.name}"?`)) return;
		try {
			await costProfilesApi.delete(cost.id);
			costs = costs.filter((other) => other.id !== cost.id);
		} catch (deleteError) { alert(String(deleteError)); }
	};

	const columns: Column<MaintenanceCostData>[] = [
		{ key: "name",                         header: "Name",              cellClass: "font-medium text-tdefault" },
		{ key: "hourly_labor_cost",             header: "Hourly Labor (€/hr)", render: (cost) => `€${cost.hourly_labor_cost}/hr` },
		{ key: "corrective_maintenance_hours",                     header: "CM Hours",              render: (cost) => `${cost.corrective_maintenance_hours} hrs`, filterable: false },
		{ key: "corrective_maintenance_additional_downtime_hours", header: "Additional Downtime",   render: (cost) => `${cost.corrective_maintenance_additional_downtime_hours} hrs`, filterable: false },
		{ key: "preventive_maintenance_hours",                     header: "PM Hours",              render: (cost) => `${cost.preventive_maintenance_hours} hrs`, filterable: false },
	];

	load();
</script>

<div class="p-6 space-y-4">
	<div class="flex items-center justify-between">
		<div>
			<h2 class="text-xl font-semibold text-theading">Costs</h2>
			<p class="text-sm text-tbody">Labor and maintenance cost parameters</p>
		</div>
		<AppButton onclick={openCreate}>Add Cost</AppButton>
	</div>

	<AppDataGrid
		data={costs}
		{columns}
		{loading}
		{error}
		emptyMessage="No costs found."
		actions={costActions}
	/>
</div>

{#snippet costActions(cost: MaintenanceCostData)}
	<div class="flex gap-1.5">
		<AppButton variant="secondary" size="sm" onclick={() => openEdit(cost)}>Edit</AppButton>
		<AppButton variant="danger-secondary" size="sm" onclick={() => remove(cost)}>Delete</AppButton>
	</div>
{/snippet}

<AppModal bind:open={modalOpen} title={editing ? "Edit Cost" : "Add Cost"} size="md">
	<AppInput label="Name" bind:value={form.name} placeholder="e.g. Standard Labor" required />
	<AppInput label="Hourly Labor Cost (€/hr)" type="number" step="0.01" bind:value={form.hourly_labor_cost} />
	<AppInput label="Corrective Maintenance Hours" type="number" step="0.1" bind:value={form.corrective_maintenance_hours} />
	<AppInput label="Additional Downtime Hours (logistics, waiting, etc.)" type="number" step="0.1" bind:value={form.corrective_maintenance_additional_downtime_hours} />
	<AppInput label="Preventive Maintenance Hours" type="number" step="0.1" bind:value={form.preventive_maintenance_hours} />
	{#snippet footer()}
		<AppButton onclick={save} loading={saving}>Save</AppButton>
		<AppButton variant="secondary" onclick={() => (modalOpen = false)}>Cancel</AppButton>
	{/snippet}
</AppModal>
