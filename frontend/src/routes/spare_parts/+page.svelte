<script lang="ts">
	import { sparePartsApi, machinesApi, costProfilesApi, type SparePart, type SparePartCreate } from "$lib/api/index.js";
	import { AppButton, AppInput, AppSelect, AppModal, AppDataGrid, AppReferenceSelector } from "$lib/components/index.js";
	import type { Column } from "$lib/components/types.js";
	import { eur } from "$lib/utils/format.js";

	let parts = $state<SparePart[]>([]);
	let machineNames = $state<Record<string, string>>({});
	let loading = $state(true);
	let error = $state<string | null>(null);

	let modalOpen = $state(false);
	let editing = $state<SparePart | null>(null);
	let saving = $state(false);

	const emptyForm = (): SparePartCreate => ({
		name: "", code: "", spare_part_type: "sensor",
		purchase_year: new Date().getFullYear(), purchase_cost: 0,
		status: "new", eta: 0, beta: 0, machine_id: null, maintenance_cost_data_id: null,
	});

	let form = $state<SparePartCreate>(emptyForm());

	const load = async () => {
		loading = true; error = null;
		try {
			const [fetchedParts, machines] = await Promise.all([
				sparePartsApi.list(),
				machinesApi.list(),
			]);
			parts = fetchedParts;
			machineNames = Object.fromEntries(machines.map((machine) => [machine.id, machine.name]));
		} catch (loadError) { error = String(loadError); }
		finally { loading = false; }
	};

	const openCreate = () => { editing = null; form = emptyForm(); modalOpen = true; };
	const openEdit = (part: SparePart) => { editing = part; form = { ...part }; modalOpen = true; };

	const save = async () => {
		saving = true;
		try {
			if (editing) {
				const updated = await sparePartsApi.update(editing.id, form);
				parts = parts.map((part) => part.id === editing!.id ? updated : part);
			} else {
				const created = await sparePartsApi.create(form);
				parts = [...parts, created];
			}
			modalOpen = false;
		} catch (saveError) { alert(String(saveError)); }
		finally { saving = false; }
	};

	const remove = async (part: SparePart) => {
		if (!confirm(`Delete spare part "${part.name}"?`)) return;
		try {
			await sparePartsApi.delete(part.id);
			parts = parts.filter((other) => other.id !== part.id);
		} catch (deleteError) { alert(String(deleteError)); }
	};

	const PART_TYPE_ITEMS = ["sensor","filter","battery","gasket","valve","roulement","kit constructor"]
		.map((partType) => ({ value: partType, name: partType }));

	const columns: Column<SparePart>[] = [
		{ key: "name", header: "Name", cellClass: "font-medium text-tdefault" },
		{ key: "code", header: "Code" },
		{ key: "spare_part_type", header: "Type", filterItems: PART_TYPE_ITEMS },
		{ key: "status", header: "Status", filterItems: [{ value: "new", name: "New" }, { value: "used", name: "Used" }] },
		{ key: "purchase_year", header: "Year" },
		{ key: "purchase_cost", header: "Cost (€)", render: (part) => eur(part.purchase_cost), align: "right", filterable: false },
		{ key: "eta", header: "η", filterable: false },
		{ key: "beta", header: "β", filterable: false },
		{ key: "machine_id", header: "Machine", render: (part) => part.machine_id ? (machineNames[part.machine_id] ?? "—") : "—", filterable: false, sortable: false },
	];

	load();
</script>

<div class="p-6 space-y-4">
	<div class="flex items-center justify-between">
		<div>
			<h2 class="text-xl font-semibold text-theading">Spare Parts</h2>
			<p class="text-sm text-tbody">Replaceable components per machine</p>
		</div>
		<AppButton onclick={openCreate}>Add Spare Part</AppButton>
	</div>

	<AppDataGrid
		data={parts}
		{columns}
		{loading}
		{error}
		emptyMessage="No spare parts found."
		actions={partActions}
	/>
</div>

{#snippet partActions(part: SparePart)}
	<div class="flex gap-1.5">
		<AppButton variant="secondary" size="sm" onclick={() => openEdit(part)}>Edit</AppButton>
		<AppButton variant="danger-secondary" size="sm" onclick={() => remove(part)}>Delete</AppButton>
	</div>
{/snippet}

<AppModal bind:open={modalOpen} title={editing ? "Edit Spare Part" : "Add Spare Part"} size="lg">
	<div class="grid grid-cols-2 gap-x-4">
		<AppInput label="Name" bind:value={form.name} placeholder="Part name" required />
		<AppInput label="Code" bind:value={form.code} placeholder="Part code" required />
		<AppSelect label="Type" bind:value={form.spare_part_type} items={PART_TYPE_ITEMS} />
		<AppSelect label="Status" bind:value={form.status} items={[{value:"new",name:"New"},{value:"used",name:"Used"}]} />
		<AppInput label="Purchase Year" type="number" bind:value={form.purchase_year} />
		<AppInput label="Purchase Cost (€)" type="number" bind:value={form.purchase_cost} />
		<AppInput label="η (Weibull scale)" type="number" step="0.01" bind:value={form.eta} />
		<AppInput label="β (Weibull shape)" type="number" step="0.01" bind:value={form.beta} />
		<AppReferenceSelector
			label="Machine"
			nullable
			value={form.machine_id ?? ""}
			loadItems={async () => (await machinesApi.list()).map((machine) => ({ value: machine.id, name: `${machine.name} (${machine.code})` }))}
			onchange={(machineId) => (form.machine_id = machineId || null)}
		/>
		<AppReferenceSelector
			label="Cost Profile"
			nullable
			value={form.maintenance_cost_data_id ?? ""}
			loadItems={async () => (await costProfilesApi.list()).map((profile) => ({ value: profile.id, name: profile.name }))}
			onchange={(profileId) => (form.maintenance_cost_data_id = profileId || null)}
		/>
	</div>
	{#snippet footer()}
		<AppButton onclick={save} loading={saving}>Save</AppButton>
		<AppButton variant="secondary" onclick={() => (modalOpen = false)}>Cancel</AppButton>
	{/snippet}
</AppModal>
