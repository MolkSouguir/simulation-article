<script lang="ts">
	import { machinesApi, machineTypesApi, costProfilesApi, pmApi, type Machine, type MachineCreate, type MachineTypeRecord } from "$lib/api/index.js";
	import { AppButton, AppInput, AppSelect, AppModal, AppDataGrid, AppReferenceSelector } from "$lib/components/index.js";
	import type { Column } from "$lib/components/types.js";
	import { eur } from "$lib/utils/format.js";

	let machines = $state<Machine[]>([]);
	let machineTypes = $state<MachineTypeRecord[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let modalOpen = $state(false);
	let editing = $state<Machine | null>(null);
	let saving = $state(false);

	// Machine types modal
	let typesModalOpen = $state(false);
	let editingType = $state<MachineTypeRecord | null>(null);
	let typeFormName = $state("");
	let typeSaving = $state(false);

	const openTypeEdit = (machineType: MachineTypeRecord) => { editingType = machineType; typeFormName = machineType.name; };

	const saveType = async () => {
		typeSaving = true;
		try {
			if (editingType) {
				const updated = await machineTypesApi.update(editingType.id, { name: typeFormName });
				machineTypes = machineTypes.map((machineType) => machineType.id === editingType!.id ? updated : machineType);
			} else {
				const created = await machineTypesApi.create({ name: typeFormName });
				machineTypes = [...machineTypes, created];
			}
			editingType = null;
			typeFormName = "";
		} catch (saveError) {
			alert(String(saveError));
		} finally {
			typeSaving = false;
		}
	};

	const removeType = async (machineType: MachineTypeRecord) => {
		if (!confirm(`Delete machine type "${machineType.name}"?`)) return;
		try {
			await machineTypesApi.delete(machineType.id);
			machineTypes = machineTypes.filter((other) => other.id !== machineType.id);
		} catch (deleteError) {
			alert(String(deleteError));
		}
	};

	const emptyForm = (): MachineCreate => ({
		name: "",
		code: "",
		machine_type: machineTypes[0]?.name ?? "",
		purchase_year: new Date().getFullYear(),
		purchase_cost: 0,
		status: "active",
		eta: 0,
		beta: 0,
		maintenance_cost_data_id: null,
		preventive_maintenance_id: null,
	});

	let form = $state<MachineCreate>(emptyForm());

	let selectedIds = $state<Set<string>>(new Set());

	// Bulk actions on the selected machines
	type BulkAction = "delete" | "status" | "weibull" | "cost_profile" | "pm_program";
	let bulkAction = $state<BulkAction | null>(null);
	let bulkOpen = $state(false);
	let bulkSaving = $state(false);

	let bulkStatus = $state<string>("active");
	let bulkEta = $state<number>(0);
	let bulkBeta = $state<number>(0);
	let bulkCostProfileId = $state<string | null>(null);
	let bulkPmId = $state<string | null>(null);

	const openBulk = (action: BulkAction) => { bulkAction = action; };

	const clearSelection = () => { selectedIds = new Set(); };

	const executeBulk = async () => {
		bulkSaving = true;
		try {
			const ids = [...selectedIds];

			if (bulkAction === "delete") {
				if (!confirm(`Delete ${ids.length} machine${ids.length !== 1 ? "s" : ""}? This cannot be undone.`)) return;
				await Promise.all(ids.map((id) => machinesApi.delete(id)));
				machines = machines.filter((machine) => !selectedIds.has(machine.id));
				clearSelection();
			} else {
				let patch: Record<string, unknown> = {};
				if (bulkAction === "status")       patch = { status: bulkStatus };
				if (bulkAction === "weibull")      patch = { eta: bulkEta, beta: bulkBeta };
				if (bulkAction === "cost_profile") patch = { maintenance_cost_data_id: bulkCostProfileId };
				if (bulkAction === "pm_program")   patch = { preventive_maintenance_id: bulkPmId };

				const updated = await Promise.all(ids.map((id) => machinesApi.update(id, patch)));
				const updatedById = Object.fromEntries(updated.map((machine) => [machine.id, machine]));
				machines = machines.map((machine) => updatedById[machine.id] ?? machine);
				clearSelection();
			}
			bulkAction = null;
		} catch (bulkError) {
			alert(String(bulkError));
		} finally {
			bulkSaving = false;
		}
	};

	const load = async () => {
		loading = true;
		error = null;
		try {
			[machines, machineTypes] = await Promise.all([machinesApi.list(), machineTypesApi.list()]);
		} catch (loadError) {
			error = String(loadError);
		} finally {
			loading = false;
		}
	};

	const openCreate = () => { editing = null; form = emptyForm(); modalOpen = true; };
	const openEdit = (machine: Machine) => { editing = machine; form = { ...machine }; modalOpen = true; };

	const save = async () => {
		saving = true;
		try {
			if (editing) {
				const updated = await machinesApi.update(editing.id, form);
				machines = machines.map((machine) => machine.id === editing!.id ? updated : machine);
			} else {
				const created = await machinesApi.create(form);
				machines = [...machines, created];
			}
			modalOpen = false;
		} catch (saveError) {
			alert(String(saveError));
		} finally {
			saving = false;
		}
	};

	const remove = async (machine: Machine) => {
		if (!confirm(`Delete machine "${machine.name}"?`)) return;
		try {
			await machinesApi.delete(machine.id);
			machines = machines.filter((other) => other.id !== machine.id);
		} catch (deleteError) {
			alert(String(deleteError));
		}
	};

	const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

	const columns: Column<Machine>[] = $derived([
		{ key: "name", header: "Name", cellClass: "font-medium text-tdefault" },
		{ key: "code", header: "Code" },
		{ key: "machine_type", header: "Type", filterItems: machineTypes.map((machineType) => ({ value: machineType.name, name: capitalize(machineType.name) })) },
		{ key: "status", header: "Status", filterItems: [{ value: "active", name: "Active" }, { value: "standby", name: "Standby" }, { value: "maintenance", name: "Maintenance" }] },
		{ key: "purchase_year", header: "Year" },
		{ key: "purchase_cost", header: "Cost (€)", render: (machine) => eur(machine.purchase_cost), align: "right", filterable: false },
		{ key: "eta", header: "η", filterable: false },
		{ key: "beta", header: "β", filterable: false },
		{ key: "spare_parts", header: "Parts", render: (machine) => String(machine.spare_parts.length), filterable: false, sortable: false },
	]);

	load();
</script>

<div class="p-6 space-y-4">
	<div class="flex items-center justify-between">
		<div>
			<h2 class="text-xl font-semibold text-theading">Machines</h2>
			<p class="text-sm text-tbody">Fleet ventilator units</p>
		</div>
		<div class="flex gap-2">
			<AppButton variant="secondary" onclick={() => { typesModalOpen = true; editingType = null; typeFormName = ""; }}>Configure Types</AppButton>
			<AppButton onclick={openCreate}>Add Machine</AppButton>
		</div>
	</div>

	<AppDataGrid
		data={machines}
		{columns}
		{loading}
		{error}
		emptyMessage="No machines found."
		selectable
		bind:selectedIds
		actions={machineActions}
	>
		{#snippet toolbar()}
			<!-- Bulk actions menu -->
			<div class="relative">
				<button
					onclick={() => (bulkOpen = !bulkOpen)}
					disabled={selectedIds.size === 0}
					class="flex items-center gap-1.5 px-3 py-2 rounded-lg border text-sm font-medium transition-colors
						{selectedIds.size > 0
							? 'border-cbase bg-secondary hover:bg-secondary/80 text-tdefault'
							: 'border-cbase bg-secondary text-tsubtle cursor-not-allowed opacity-50'}"
				>
					Bulk Actions
					{#if selectedIds.size > 0}
						<span class="bg-brand text-white text-xs rounded-full px-1.5 py-0.5 leading-none">{selectedIds.size}</span>
					{/if}
					<svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5 text-tsubtle" viewBox="0 0 20 20" fill="currentColor">
						<path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
					</svg>
				</button>

				{#if bulkOpen}
					<div
						role="menu"
						tabindex="-1"
						class="absolute left-0 top-full mt-1 z-20 min-w-44 rounded-lg border border-cbase bg-card shadow-lg py-1"
						onmouseleave={() => (bulkOpen = false)}
					>
						<button class="w-full px-4 py-2 text-left text-sm text-tdefault hover:bg-secondary transition-colors" onclick={() => { bulkOpen = false; openBulk("status"); }}>Set Status</button>
						<button class="w-full px-4 py-2 text-left text-sm text-tdefault hover:bg-secondary transition-colors" onclick={() => { bulkOpen = false; openBulk("weibull"); }}>Set β / η</button>
						<button class="w-full px-4 py-2 text-left text-sm text-tdefault hover:bg-secondary transition-colors" onclick={() => { bulkOpen = false; openBulk("cost_profile"); }}>Set Cost Profile</button>
						<button class="w-full px-4 py-2 text-left text-sm text-tdefault hover:bg-secondary transition-colors" onclick={() => { bulkOpen = false; openBulk("pm_program"); }}>Set PM Program</button>
						<div class="border-t border-cbase my-1"></div>
						<button class="w-full px-4 py-2 text-left text-sm text-danger hover:bg-secondary transition-colors" onclick={() => { bulkOpen = false; bulkAction = "delete"; executeBulk(); }}>Delete Selected</button>
					</div>
				{/if}
			</div>
		{/snippet}
	</AppDataGrid>
</div>

{#snippet machineActions(machine: Machine)}
	<div class="flex gap-1.5">
		<AppButton variant="secondary" size="sm" onclick={() => openEdit(machine)}>Edit</AppButton>
		<AppButton variant="danger-secondary" size="sm" onclick={() => remove(machine)}>Delete</AppButton>
	</div>
{/snippet}

<!-- Bulk: set status -->
<AppModal bind:open={() => bulkAction === "status", (isOpen) => { if (!isOpen) bulkAction = null; }} title="Set Status — {selectedIds.size} machines" size="sm">
	<AppSelect
		label="Status"
		bind:value={bulkStatus}
		items={[
			{ value: "active", name: "Active" },
			{ value: "standby", name: "Standby" },
			{ value: "maintenance", name: "Maintenance" },
		]}
	/>
	{#snippet footer()}
		<AppButton onclick={executeBulk} loading={bulkSaving}>Apply</AppButton>
		<AppButton variant="secondary" onclick={() => (bulkAction = null)}>Cancel</AppButton>
	{/snippet}
</AppModal>

<!-- Bulk: set Weibull parameters -->
<AppModal bind:open={() => bulkAction === "weibull", (isOpen) => { if (!isOpen) bulkAction = null; }} title="Set β / η — {selectedIds.size} machines" size="sm">
	<AppInput label="η (Weibull scale, years)" type="number" step="0.01" bind:value={bulkEta} />
	<AppInput label="β (Weibull shape)" type="number" step="0.01" bind:value={bulkBeta} />
	{#snippet footer()}
		<AppButton onclick={executeBulk} loading={bulkSaving}>Apply</AppButton>
		<AppButton variant="secondary" onclick={() => (bulkAction = null)}>Cancel</AppButton>
	{/snippet}
</AppModal>

<!-- Bulk: set cost profile -->
<AppModal bind:open={() => bulkAction === "cost_profile", (isOpen) => { if (!isOpen) bulkAction = null; }} title="Set Cost Profile — {selectedIds.size} machines" size="sm">
	<AppReferenceSelector
		label="Cost Profile"
		nullable
		value={bulkCostProfileId ?? ""}
		loadItems={async () => (await costProfilesApi.list()).map((profile) => ({ value: profile.id, name: profile.name }))}
		onchange={(profileId) => (bulkCostProfileId = profileId || null)}
	/>
	{#snippet footer()}
		<AppButton onclick={executeBulk} loading={bulkSaving}>Apply</AppButton>
		<AppButton variant="secondary" onclick={() => (bulkAction = null)}>Cancel</AppButton>
	{/snippet}
</AppModal>

<!-- Bulk: set PM program -->
<AppModal bind:open={() => bulkAction === "pm_program", (isOpen) => { if (!isOpen) bulkAction = null; }} title="Set PM Program — {selectedIds.size} machines" size="sm">
	<AppReferenceSelector
		label="PM Program"
		nullable
		value={bulkPmId ?? ""}
		loadItems={async () => (await pmApi.list()).map((schedule) => ({ value: schedule.id, name: `${schedule.name} (${schedule.years_interval} yr interval)` }))}
		onchange={(scheduleId) => (bulkPmId = scheduleId || null)}
	/>
	{#snippet footer()}
		<AppButton onclick={executeBulk} loading={bulkSaving}>Apply</AppButton>
		<AppButton variant="secondary" onclick={() => (bulkAction = null)}>Cancel</AppButton>
	{/snippet}
</AppModal>

<!-- Add / edit machine -->
<AppModal bind:open={modalOpen} title={editing ? "Edit Machine" : "Add Machine"} size="lg">
	<div class="grid grid-cols-2 gap-x-4">
		<AppInput label="Name" bind:value={form.name} placeholder="Machine name" required />
		<AppInput label="Code" bind:value={form.code} placeholder="Unique code" required />
		<AppSelect
			label="Machine Type"
			bind:value={form.machine_type}
			items={machineTypes.map((machineType) => ({ value: machineType.name, name: capitalize(machineType.name) }))}
		/>
		<AppSelect
			label="Status"
			bind:value={form.status}
			items={[
				{ value: "active", name: "Active" },
				{ value: "standby", name: "Standby" },
				{ value: "maintenance", name: "Maintenance" },
			]}
		/>
		<AppInput label="Purchase Year" type="number" bind:value={form.purchase_year} />
		<AppInput label="Purchase Cost (€)" type="number" bind:value={form.purchase_cost} />
		<AppInput label="η (Weibull scale)" type="number" step="0.01" bind:value={form.eta} />
		<AppInput label="β (Weibull shape)" type="number" step="0.01" bind:value={form.beta} />
		<AppReferenceSelector
			label="Cost Profile"
			nullable
			value={form.maintenance_cost_data_id ?? ""}
			loadItems={async () => (await costProfilesApi.list()).map((profile) => ({ value: profile.id, name: profile.name }))}
			onchange={(profileId) => (form.maintenance_cost_data_id = profileId || null)}
		/>
		<AppReferenceSelector
			label="PM Program"
			nullable
			value={form.preventive_maintenance_id ?? ""}
			loadItems={async () => (await pmApi.list()).map((schedule) => ({ value: schedule.id, name: `${schedule.name} (${schedule.years_interval} yr interval)` }))}
			onchange={(scheduleId) => (form.preventive_maintenance_id = scheduleId || null)}
		/>
	</div>
	{#snippet footer()}
		<AppButton onclick={save} loading={saving}>Save</AppButton>
		<AppButton variant="secondary" onclick={() => (modalOpen = false)}>Cancel</AppButton>
	{/snippet}
</AppModal>

<!-- Machine types -->
<AppModal bind:open={typesModalOpen} title="Machine Types" size="sm">
	<div class="space-y-4">
		<div class="space-y-1">
			{#each machineTypes as machineType}
				<div class="flex items-center justify-between px-3 py-2 rounded-lg border border-cbase bg-secondary/50">
					{#if editingType?.id === machineType.id}
						<AppInput
							wrapperClass="flex-1 mr-2"
							class="py-1 text-sm"
							bind:value={typeFormName}
							onkeydown={(event: KeyboardEvent) => { if (event.key === "Enter") saveType(); if (event.key === "Escape") editingType = null; }}
						/>
						<div class="flex gap-1.5 shrink-0">
							<AppButton size="sm" onclick={saveType} loading={typeSaving}>Save</AppButton>
							<AppButton size="sm" variant="secondary" onclick={() => (editingType = null)}>Cancel</AppButton>
						</div>
					{:else}
						<span class="text-sm text-tdefault capitalize">{machineType.name}</span>
						<div class="flex gap-1.5 shrink-0">
							<AppButton size="sm" variant="secondary" onclick={() => openTypeEdit(machineType)}>Edit</AppButton>
							<AppButton size="sm" variant="danger-secondary" onclick={() => removeType(machineType)}>Delete</AppButton>
						</div>
					{/if}
				</div>
			{/each}
			{#if machineTypes.length === 0}
				<p class="text-sm text-tsubtle text-center py-2">No machine types defined.</p>
			{/if}
		</div>

		<!-- New type -->
		{#if editingType === null}
			<div class="flex gap-2 pt-1 border-t border-cbase">
				<AppInput
					wrapperClass="flex-1"
					placeholder="New type name…"
					bind:value={typeFormName}
					onkeydown={(event: KeyboardEvent) => { if (event.key === "Enter" && typeFormName.trim()) saveType(); }}
				/>
				<AppButton onclick={saveType} loading={typeSaving} disabled={!typeFormName.trim()}>Add</AppButton>
			</div>
		{/if}
	</div>
	{#snippet footer()}
		<AppButton variant="secondary" onclick={() => (typesModalOpen = false)}>Close</AppButton>
	{/snippet}
</AppModal>
