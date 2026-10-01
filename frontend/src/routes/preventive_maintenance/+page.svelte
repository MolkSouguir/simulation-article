<script lang="ts">
	import {
		pmApi, pmCycleYearsApi,
		type PreventiveMaintenance, type PMCycleYear, type PMCycleYearCreate, type SparePartType,
	} from "$lib/api/index.js";
	import { AppButton, AppCheckbox, AppInput, AppModal, AppPagination } from "$lib/components/index.js";

	const ALL_PART_TYPES: SparePartType[] = [
		"sensor", "filter", "battery", "gasket", "valve", "roulement", "kit constructor",
	];

	let schedules = $state<PreventiveMaintenance[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let page = $state(1);
	let pageSize = $state(10);

	const paginated = $derived(schedules.slice((page - 1) * pageSize, page * pageSize));

	// PM schedule modal
	let pmModalOpen = $state(false);
	let pmEditing = $state<PreventiveMaintenance | null>(null);
	let pmForm = $state({ name: "", years_interval: 1 });
	let pmSaving = $state(false);

	// Cycle year modal
	let cycleYearModalOpen = $state(false);
	let cycleYearScheduleId = $state<string | null>(null);
	let editingCycleYear = $state<PMCycleYear | null>(null);
	let cycleYearForm = $state<PMCycleYearCreate>({
		order: 1, preventive_maintenance_hours: 1, hourly_labor_cost: 60, pm_year_cost: 0, parts: [],
	});
	let cycleYearSaving = $state(false);

	const load = async () => {
		loading = true; error = null;
		try { schedules = await pmApi.list(); }
		catch (loadError) { error = String(loadError); }
		finally { loading = false; }
	}

	const openCreatePm = () => { pmEditing = null; pmForm = { name: "", years_interval: 1 }; pmModalOpen = true; };
	const openEditPm = (schedule: PreventiveMaintenance) => {
		pmEditing = schedule;
		pmForm = { name: schedule.name, years_interval: schedule.years_interval };
		pmModalOpen = true;
	};

	const savePm = async () => {
		pmSaving = true;
		try {
			if (pmEditing) {
				const updated = await pmApi.update(pmEditing.id, pmForm);
				schedules = schedules.map((schedule) => schedule.id === pmEditing!.id ? updated : schedule);
			} else {
				const created = await pmApi.create({ ...pmForm, cycle_years: [] });
				schedules = [...schedules, created];
			}
			pmModalOpen = false;
		} catch (saveError) { alert(String(saveError)); }
		finally { pmSaving = false; }
	}

	const removePm = async (schedule: PreventiveMaintenance) => {
		if (!confirm(`Delete PM schedule "${schedule.name}" and all its cycle years?`)) return;
		try {
			await pmApi.delete(schedule.id);
			schedules = schedules.filter((other) => other.id !== schedule.id);
		}
		catch (deleteError) { alert(String(deleteError)); }
	}

	const openCreateCycleYear = (scheduleId: string, nextOrder: number) => {
		cycleYearScheduleId = scheduleId; editingCycleYear = null;
		cycleYearForm = { order: nextOrder, preventive_maintenance_hours: 1, hourly_labor_cost: 60, pm_year_cost: 0, parts: [] };
		cycleYearModalOpen = true;
	}

	const openEditCycleYear = (scheduleId: string, cycleYear: PMCycleYear) => {
		cycleYearScheduleId = scheduleId; editingCycleYear = cycleYear;
		cycleYearForm = {
			order: cycleYear.order, preventive_maintenance_hours: cycleYear.preventive_maintenance_hours,
			hourly_labor_cost: cycleYear.hourly_labor_cost, pm_year_cost: cycleYear.pm_year_cost,
			parts: cycleYear.parts.map((part) => part.spare_part_type),
		};
		cycleYearModalOpen = true;
	}

	const saveCycleYear = async () => {
		if (cycleYearScheduleId == null) return;
		cycleYearSaving = true;
		try {
			if (editingCycleYear) {
				const updated = await pmCycleYearsApi.update(cycleYearScheduleId, editingCycleYear.id, cycleYearForm);
				schedules = schedules.map((schedule) =>
					schedule.id !== cycleYearScheduleId ? schedule : {
						...schedule,
						cycle_years: schedule.cycle_years.map((cycleYear) => cycleYear.id === editingCycleYear!.id ? updated : cycleYear),
					}
				);
			} else {
				const created = await pmCycleYearsApi.create(cycleYearScheduleId, cycleYearForm);
				schedules = schedules.map((schedule) =>
					schedule.id !== cycleYearScheduleId ? schedule : { ...schedule, cycle_years: [...schedule.cycle_years, created] }
				);
			}
			cycleYearModalOpen = false;
		} catch (saveError) { alert(String(saveError)); }
		finally { cycleYearSaving = false; }
	}

	const removeCycleYear = async (scheduleId: string, cycleYear: PMCycleYear) => {
		if (!confirm(`Delete cycle year ${cycleYear.order}?`)) return;
		try {
			await pmCycleYearsApi.delete(scheduleId, cycleYear.id);
			schedules = schedules.map((schedule) =>
				schedule.id !== scheduleId
					? schedule
					: { ...schedule, cycle_years: schedule.cycle_years.filter((other) => other.id !== cycleYear.id) }
			);
		}
		catch (deleteError) { alert(String(deleteError)); }
	}

	const togglePart = (partType: SparePartType) => {
		cycleYearForm.parts = cycleYearForm.parts.includes(partType)
			? cycleYearForm.parts.filter((selected) => selected !== partType)
			: [...cycleYearForm.parts, partType];
	}

	load();
</script>

<div class="p-6 space-y-4">
	<div class="flex items-center justify-between">
		<div>
			<h2 class="text-xl font-semibold text-theading">PM Schedules</h2>
			<p class="text-sm text-tbody">Preventive maintenance schedules and cycle definitions</p>
		</div>
		<AppButton onclick={openCreatePm}>Add PM Schedule</AppButton>
	</div>

	{#if loading}
		<p class="text-sm text-tbody">Loading...</p>
	{:else if error}
		<p class="text-sm text-danger">{error}</p>
	{:else}
		<div class="space-y-4">
			{#each paginated as schedule}
				<div class="rounded-lg border border-cbase overflow-hidden">
					<div class="flex items-center justify-between px-4 py-3 bg-secondary border-b border-cbase">
						<div>
							<span class="font-medium text-tdefault">{schedule.name}</span>
							<span class="ml-3 text-sm text-tsubtle">
								{schedule.years_interval} year interval · {schedule.cycle_years.length} cycle year(s)
							</span>
						</div>
						<div class="flex gap-1.5">
							<AppButton variant="brand-secondary" size="sm"
								onclick={() => openCreateCycleYear(schedule.id, schedule.cycle_years.length + 1)}>
								Add Cycle Year
							</AppButton>
							<AppButton variant="secondary" size="sm" onclick={() => openEditPm(schedule)}>Edit</AppButton>
							<AppButton variant="danger-secondary" size="sm" onclick={() => removePm(schedule)}>Delete</AppButton>
						</div>
					</div>

					{#if schedule.cycle_years.length > 0}
						<table class="w-full text-sm">
							<thead class="border-b border-cbase">
								<tr>
									{#each ["Order","PM Hours","Labor (€/hr)","Year Cost (€)","Parts Replaced",""] as header}
										<th class="px-4 py-2.5 text-left font-medium text-tsubtle">{header}</th>
									{/each}
								</tr>
							</thead>
							<tbody class="divide-y divide-cbase">
								{#each schedule.cycle_years as cycleYear}
									<tr class="hover:bg-secondary transition-colors">
										<td class="px-4 py-2.5 text-tbody">{cycleYear.order}</td>
										<td class="px-4 py-2.5 text-tbody">{cycleYear.preventive_maintenance_hours} hrs</td>
										<td class="px-4 py-2.5 text-tbody">€{cycleYear.hourly_labor_cost}/hr</td>
										<td class="px-4 py-2.5 text-tbody">€{cycleYear.pm_year_cost.toLocaleString()}</td>
										<td class="px-4 py-2.5 text-tbody">
											{cycleYear.parts.length > 0 ? cycleYear.parts.map((part) => part.spare_part_type).join(", ") : "—"}
										</td>
										<td class="px-4 py-2.5">
											<div class="flex gap-1.5">
												<AppButton variant="secondary" size="sm" onclick={() => openEditCycleYear(schedule.id, cycleYear)}>Edit</AppButton>
												<AppButton variant="danger-secondary" size="sm" onclick={() => removeCycleYear(schedule.id, cycleYear)}>Delete</AppButton>
											</div>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					{:else}
						<p class="px-4 py-4 text-sm text-tsubtle">No cycle years defined yet.</p>
					{/if}
				</div>
			{:else}
				<p class="text-sm text-tbody">No PM schedules found.</p>
			{/each}
		</div>
		<AppPagination total={schedules.length} bind:page bind:pageSize pageSizeOptions={[5, 10, 25]} />
	{/if}
</div>

<AppModal bind:open={pmModalOpen} title={pmEditing ? "Edit PM Schedule" : "Add PM Schedule"} size="sm">
	<AppInput label="Name" bind:value={pmForm.name} placeholder="e.g. Cycle" required />
	<AppInput label="Cycle Interval (years)" type="number" bind:value={pmForm.years_interval} min="1" wrapperClass="mb-0" />
	{#snippet footer()}
		<AppButton variant="secondary" onclick={() => (pmModalOpen = false)}>Cancel</AppButton>
		<AppButton onclick={savePm} loading={pmSaving}>Save</AppButton>
	{/snippet}
</AppModal>

<AppModal bind:open={cycleYearModalOpen} title={editingCycleYear ? `Edit Cycle Year ${editingCycleYear.order}` : "Add Cycle Year"} size="md">
	<div class="grid grid-cols-2 gap-x-4">
		<AppInput label="Order" type="number" bind:value={cycleYearForm.order} min="1" />
		<AppInput label="PM Hours" type="number" step="0.5" bind:value={cycleYearForm.preventive_maintenance_hours} />
		<AppInput label="Labor Cost (€/hr)" type="number" bind:value={cycleYearForm.hourly_labor_cost} />
		<AppInput label="Total Year Cost (€)" type="number" bind:value={cycleYearForm.pm_year_cost} wrapperClass="mb-5" />
	</div>
	<p class="text-sm font-medium text-tdefault mb-2">Parts replaced this cycle year</p>
	<div class="grid grid-cols-2 gap-1">
		{#each ALL_PART_TYPES as partType}
			<label class="flex items-center gap-2.5 cursor-pointer rounded-lg border px-3 py-2 text-sm transition-colors
				{cycleYearForm.parts.includes(partType) ? 'border-brand bg-brand-light text-brand' : 'border-cbase hover:bg-secondary text-tdefault'}">
				<AppCheckbox checked={cycleYearForm.parts.includes(partType)} onchange={() => togglePart(partType)} wrapperClass="" />
				{partType}
			</label>
		{/each}
	</div>
	{#snippet footer()}
		<AppButton variant="secondary" onclick={() => (cycleYearModalOpen = false)}>Cancel</AppButton>
		<AppButton onclick={saveCycleYear} loading={cycleYearSaving}>Save</AppButton>
	{/snippet}
</AppModal>
