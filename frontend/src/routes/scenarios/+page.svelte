<script lang="ts">
	import {
		scenarioProfilesApi,
		machineTypesApi,
		type ScenarioProfile,
		type ScenarioConfig,
		type ScenarioCriterion,
		type ScenarioAlternative,
		type DecisionMethod,
		type SimulationBehavior,
		type MachineTypeRecord,
		DEFAULT_SIMULATION_BEHAVIOR,
	} from "$lib/api/index.js";
	import { AppButton, AppInput, AppModal, AppCheckbox, AppDataGrid, AppSelect } from "$lib/components/index.js";
	import type { Column } from "$lib/components/types.js";

	// Same criteria as on the Simulation page
	const CATALOG: ScenarioCriterion[] = [
		{ attribute_name: "normal_availability", name: "Available Machines — Normal",   input_type: "threshold_int", minimize: false },
		{ attribute_name: "crisis_availability", name: "Available Machines — Crisis",   input_type: "threshold_int", minimize: false },
		{ attribute_name: "normal_hours_availability", name: "Availability — Normal",   input_type: "daily_hours",   minimize: false },
		{ attribute_name: "crisis_hours_availability", name: "Availability — Crisis",   input_type: "daily_hours",   minimize: false },
		{ attribute_name: "total_cost",          name: "Total Cost",              input_type: "computed",      minimize: true  },
		{ attribute_name: "staff_satisfaction",  name: "Staff Satisfaction",      input_type: "qualitative",   minimize: false },
		{ attribute_name: "clinical_features",   name: "Sensitivity to Obsolescence",          input_type: "qualitative", minimize: false },
		{ attribute_name: "logistics_procurement", name: "Easiness of Logistics & Procurement", input_type: "qualitative", minimize: false },
	];

	const SAATY_OPTIONS = [
		{ value: 9,       label: "9 — Absolute" },
		{ value: 7,       label: "7 — Very strong" },
		{ value: 5,       label: "5 — Strong" },
		{ value: 3,       label: "3 — Moderate" },
		{ value: 1,       label: "1 — Equal" },
		{ value: 1/3,     label: "1/3 — Moderate ↓" },
		{ value: 1/5,     label: "1/5 — Strong ↓" },
		{ value: 1/7,     label: "1/7 — Very strong ↓" },
		{ value: 1/9,     label: "1/9 — Absolute ↓" },
	];

	// AHP comparisons, upper triangle only, keyed by "rowAttribute:columnAttribute"
	let pairwiseValues = $state<Record<string, number>>({});

	// TOPSIS / ELECTRE II weights, keyed by attribute_name
	let topsisWeights = $state<Record<string, number>>({});
	const getTW = (attribute: string) => topsisWeights[attribute] ?? 1;
	const setTW = (attribute: string, weight: number) => { topsisWeights = { ...topsisWeights, [attribute]: weight }; };
	const buildDirectWeights = (criteriaList: ScenarioCriterion[]) => criteriaList.map((criterion) => getTW(criterion.attribute_name));

	const pwKey = (rowAttribute: string, columnAttribute: string) => `${rowAttribute}:${columnAttribute}`;
	const getPW = (rowAttribute: string, columnAttribute: string) => pairwiseValues[pwKey(rowAttribute, columnAttribute)] ?? 1;
	const setPW = (rowAttribute: string, columnAttribute: string, value: number) => {
		pairwiseValues = { ...pairwiseValues, [pwKey(rowAttribute, columnAttribute)]: value };
	};
	const buildUpperTriangle = (criteriaList: ScenarioCriterion[]) => {
		const triangle: number[] = [];
		for (let row = 0; row < criteriaList.length; row++)
			for (let column = row + 1; column < criteriaList.length; column++)
				triangle.push(getPW(criteriaList[row].attribute_name, criteriaList[column].attribute_name));
		return triangle;
	};
	const loadPairwiseFromTriangle = (criteriaList: ScenarioCriterion[], triangle: number[] | undefined) => {
		const values: Record<string, number> = {};
		if (!triangle) return values;
		let triangleIndex = 0;
		for (let row = 0; row < criteriaList.length; row++)
			for (let column = row + 1; column < criteriaList.length; column++)
				values[pwKey(criteriaList[row].attribute_name, criteriaList[column].attribute_name)] = triangle[triangleIndex++] ?? 1;
		return values;
	};

	let profiles = $state<ScenarioProfile[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	const METHODS: { value: DecisionMethod; label: string }[] = [
		{ value: "AHP",      label: "AHP — Analytic Hierarchy Process" },
		{ value: "TOPSIS",   label: "TOPSIS" },
		{ value: "ELECTRE2", label: "ELECTRE II" },
		{ value: "ELECTRE",  label: "ELECTRE (not implemented)" },
	];

	// Profile modal
	let modalOpen = $state(false);
	let editing = $state<ScenarioProfile | null>(null);
	let saving = $state(false);
	let profileName = $state("");
	let method = $state<DecisionMethod>("AHP");

	// Criteria being edited in the modal
	let criteria = $state<ScenarioCriterion[]>([]);
	let criteriaToAdd = $state("");
	const topsisTotal = $derived(criteria.reduce((total, criterion) => total + getTW(criterion.attribute_name), 0));

	// Simulation settings being edited in the modal
	let simBehavior = $state<SimulationBehavior>({ ...DEFAULT_SIMULATION_BEHAVIOR });

	const WEEKDAYS = [
		{ index: 0, label: "Mon" }, { index: 1, label: "Tue" }, { index: 2, label: "Wed" },
		{ index: 3, label: "Thu" }, { index: 4, label: "Fri" }, { index: 5, label: "Sat" },
		{ index: 6, label: "Sun" },
	];

	const toggleSessionDay = (dayIndex: number) => {
		const days = simBehavior.session_days;
		simBehavior = {
			...simBehavior,
			session_days: days.includes(dayIndex) ? days.filter((day) => day !== dayIndex) : [...days, dayIndex].sort(),
		};
	};

	const shiftDurationsTotal = $derived(simBehavior.shift_durations.reduce((total, hours) => total + hours, 0));

	const addShift = () => {
		simBehavior = { ...simBehavior, shift_durations: [...simBehavior.shift_durations, 0] };
	};
	const removeShift = (shiftIndex: number) => {
		simBehavior = {
			...simBehavior,
			shift_durations: simBehavior.shift_durations.filter((_, index) => index !== shiftIndex),
		};
	};

	let machineTypes = $state<MachineTypeRecord[]>([]);
	machineTypesApi.list().then((types) => { machineTypes = types; });

	// Alternatives being edited in the modal
	let alternatives = $state<ScenarioAlternative[]>([]);

	const availableCatalog = $derived(
		CATALOG.filter((entry) => !criteria.some((selected) => selected.attribute_name === entry.attribute_name))
	);

	// Criteria that need a value per alternative (everything but the computed ones)
	const inputCriteria = $derived(criteria.filter((criterion) => criterion.input_type !== "computed"));

	const emptyConfig = (): ScenarioConfig => ({
		method: "AHP",
		simulation: { ...DEFAULT_SIMULATION_BEHAVIOR, machine_type: "ventilator" },
		criteria: CATALOG.map((entry) => ({ ...entry })),
		alternatives: [
			{ name: "Alt-1", machine_number: 38, replacement_period: 7, scores: { normal_availability: 36, crisis_availability: 44, staff_satisfaction: 7.5, clinical_features: 10, logistics_procurement: 7.5 } },
		],
		pairwise_upper_triangle: [],
	});

	const openCreate = () => {
		editing = null;
		profileName = "";
		method = "AHP";
		const config = emptyConfig();
		simBehavior = { ...config.simulation };
		criteria = config.criteria.map((criterion) => ({ ...criterion }));
		alternatives = config.alternatives.map((alternative) => ({ ...alternative, scores: { ...alternative.scores } }));
		pairwiseValues = {};
		topsisWeights = {};
		modalOpen = true;
	};

	const openEdit = (profile: ScenarioProfile) => {
		editing = profile;
		profileName = profile.name;
		method = profile.config.method ?? "AHP";
		const savedSimulation = Object.fromEntries(
			Object.entries(profile.config.simulation ?? {}).filter(([, value]) => value !== undefined)
		);
		simBehavior = { ...DEFAULT_SIMULATION_BEHAVIOR, ...savedSimulation };
		criteria = profile.config.criteria.map((criterion) => ({ ...criterion }));
		alternatives = profile.config.alternatives.map((alternative) => {
			const scores: Record<string, number> = {};
			CATALOG.forEach((entry) => { scores[entry.attribute_name] = alternative.scores?.[entry.attribute_name] ?? 0; });
			return { ...alternative, scores };
		});
		pairwiseValues = loadPairwiseFromTriangle(criteria, profile.config.pairwise_upper_triangle);
		const weights: Record<string, number> = {};
		if (profile.config.direct_weights) {
			profile.config.criteria.forEach((criterion, index) => {
				weights[criterion.attribute_name] = profile.config.direct_weights![index] ?? 1;
			});
		}
		topsisWeights = weights;
		modalOpen = true;
	};

	const addCriterion = () => {
		const entry = CATALOG.find((catalogEntry) => catalogEntry.attribute_name === criteriaToAdd);
		if (!entry) return;
		criteria = [...criteria, { ...entry }];
		criteriaToAdd = "";
	};

	const removeCriterion = (attribute: string) => {
		criteria = criteria.filter((criterion) => criterion.attribute_name !== attribute);
		alternatives = alternatives.map((alternative) => {
			const { [attribute]: _, ...remainingScores } = alternative.scores;
			return { ...alternative, scores: remainingScores };
		});
	};

	const makeDefaultScores = (): Record<string, number> => {
		const scores: Record<string, number> = {};
		for (const criterion of inputCriteria) {
			scores[criterion.attribute_name] = criterion.input_type === "threshold_int" ? 36 : criterion.input_type === "daily_hours" ? 24 : 0;
		}
		return scores;
	};

	// A new row copies the previous one, so similar alternatives are quick to enter
	const addRow = () => {
		const last = alternatives[alternatives.length - 1];
		alternatives = [...alternatives, {
			name: `Alt-${alternatives.length + 1}`,
			machine_number: last?.machine_number ?? 38,
			replacement_period: last?.replacement_period ?? 7,
			scores: last ? { ...last.scores } : makeDefaultScores(),
		}];
	};

	const removeRow = (rowIndex: number) => {
		alternatives = alternatives.filter((_, index) => index !== rowIndex);
	};

	const save = async () => {
		saving = true;
		try {
			// Only keep the scores of criteria that are still selected
			const activeKeys = new Set(criteria.map((criterion) => criterion.attribute_name));
			const cleanedAlternatives = alternatives.map((alternative) => ({
				...alternative,
				scores: Object.fromEntries(Object.entries(alternative.scores).filter(([attribute]) => activeKeys.has(attribute))),
			}));
			const config: ScenarioConfig = {
				method,
				simulation: simBehavior,
				criteria,
				alternatives: cleanedAlternatives,
				...(method === "AHP" ? { pairwise_upper_triangle: buildUpperTriangle(criteria) } : {}),
				...(method === "TOPSIS" || method === "ELECTRE2" ? { direct_weights: buildDirectWeights(criteria) } : {}),
			};
			if (editing) {
				const updated = await scenarioProfilesApi.update(editing.id, { name: profileName, config });
				profiles = profiles.map((profile) => profile.id === editing!.id ? updated : profile);
			} else {
				const created = await scenarioProfilesApi.create({ name: profileName, config });
				profiles = [...profiles, created];
			}
			modalOpen = false;
		} catch (saveError) {
			alert(String(saveError));
		} finally {
			saving = false;
		}
	};

	const remove = async (profile: ScenarioProfile) => {
		if (!confirm(`Delete profile "${profile.name}"?`)) return;
		try {
			await scenarioProfilesApi.delete(profile.id);
			profiles = profiles.filter((other) => other.id !== profile.id);
		} catch (deleteError) {
			alert(String(deleteError));
		}
	};

	const load = async () => {
		loading = true; error = null;
		try { profiles = await scenarioProfilesApi.list(); }
		catch (loadError) { error = String(loadError); }
		finally { loading = false; }
	};

	const columns: Column<ScenarioProfile>[] = [
		{ key: "name", header: "Name", cellClass: "font-medium text-tdefault" },
		{ key: "config", header: "Criteria",     render: (profile) => String(profile.config.criteria.length), filterable: false, sortable: false },
		{ key: "config", header: "Alternatives", render: (profile) => String(profile.config.alternatives.length), filterable: false, sortable: false },
	];

	load();
</script>

<div class="p-6 space-y-4">
	<div class="flex items-center justify-between">
		<div>
			<h2 class="text-xl font-semibold text-theading">Scenario Profiles</h2>
			<p class="text-sm text-tbody">Saved criteria and alternatives for simulation runs</p>
		</div>
		<AppButton onclick={openCreate}>New Profile</AppButton>
	</div>

	<AppDataGrid
		data={profiles}
		{columns}
		{loading}
		{error}
		emptyMessage="No scenario profiles yet."
		actions={profileActions}
	/>
</div>

{#snippet profileActions(profile: ScenarioProfile)}
	<div class="flex gap-1.5">
		<AppButton variant="secondary" size="sm" onclick={() => openEdit(profile)}>Edit</AppButton>
		<AppButton variant="danger-secondary" size="sm" onclick={() => remove(profile)}>Delete</AppButton>
	</div>
{/snippet}

<AppModal bind:open={modalOpen} title={editing ? "Edit Profile" : "New Scenario Profile"} size="screen">
	<div class="space-y-6">
		<AppInput label="Profile Name" bind:value={profileName} placeholder="e.g. Ventilator Fleet 2025" required wrapperClass="w-72" />

		<AppSelect
			label="Decision Method"
			bind:value={method}
			items={METHODS.map((methodOption) => ({ value: methodOption.value, name: methodOption.label }))}
			wrapperClass="w-72"
		/>

		{#if method === "ELECTRE"}
			<div class="rounded-lg border border-cbase bg-secondary p-6 text-center space-y-1">
				<p class="text-sm font-semibold text-tdefault">ELECTRE — Coming Soon</p>
				<p class="text-xs text-tsubtle">This method is not yet implemented. You can still configure your alternatives below.</p>
			</div>
		{/if}

		<!-- Simulation behaviour -->
		<div class="rounded-lg border border-cbase bg-secondary p-4 space-y-4">
			<h4 class="text-sm font-semibold text-tdefault">Simulation Behavior</h4>
			<div class="flex items-center gap-6 flex-wrap">
				<AppSelect
					label="Machine Type"
					value={simBehavior.machine_type}
					onchange={(selectedType) => { simBehavior = { ...simBehavior, machine_type: selectedType }; }}
					items={machineTypes.map((machineType) => ({ value: machineType.name, name: machineType.name }))}
					wrapperClass="w-48"
				/>

				<div class="flex flex-col gap-1">
					<span class="text-xs font-medium text-tsubtle">Active Days</span>
					<div class="flex gap-1">
						{#each WEEKDAYS as day}
							<button
								onclick={() => toggleSessionDay(day.index)}
								class="w-9 py-1 rounded text-xs font-medium border transition-colors
									{simBehavior.session_days.includes(day.index)
										? 'bg-brand text-white border-brand'
										: 'bg-card text-tsubtle border-cbase hover:border-brand/50'}"
							>{day.label}</button>
						{/each}
					</div>
				</div>

				<div class="flex flex-col gap-1">
					<div class="flex items-end gap-2">
						{#each simBehavior.shift_durations as duration, shiftIndex}
							<div class="flex items-end gap-1">
								<AppInput
									label="Shift {shiftIndex + 1}"
									type="number" min="0.5" max="24" step="0.5"
									bind:value={simBehavior.shift_durations[shiftIndex]}
									class="w-16 {shiftDurationsTotal > 24 ? 'border-red-500' : ''}"
									wrapperClass="mb-0"
								/>
								{#if simBehavior.shift_durations.length > 1}
									<button
										onclick={() => removeShift(shiftIndex)}
										class="text-xs text-danger opacity-50 hover:opacity-100 transition-opacity px-1 pb-2.5"
										title="Remove shift"
									>✕</button>
								{/if}
							</div>
						{/each}
						<div class="pb-0">
							<AppButton onclick={addShift} size="sm">Add Shift</AppButton>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Criteria -->
		{#if method === "AHP" || method === "TOPSIS" || method === "ELECTRE2"}
			<div>
				<div class="flex items-center justify-between mb-2">
					<h4 class="text-sm font-semibold text-tdefault">Criteria</h4>
					<div class="flex gap-2">
						<select
							bind:value={criteriaToAdd}
							class="app-input text-sm py-1 px-2"
						>
							<option value="">Add criterion…</option>
							{#each availableCatalog as catalogEntry}
								<option value={catalogEntry.attribute_name}>{catalogEntry.name}</option>
							{/each}
						</select>
						<AppButton size="sm" onclick={addCriterion} disabled={!criteriaToAdd}>Add</AppButton>
					</div>
				</div>
				<div class="rounded-lg border border-cbase overflow-hidden">
					<table class="w-full text-sm">
						<thead class="bg-secondary border-b border-cbase">
							<tr>
								<th class="px-4 py-2 text-left font-medium text-tsubtle">Criterion</th>
								<th class="px-4 py-2 text-left font-medium text-tsubtle">Type</th>
								<th class="px-4 py-2 text-left font-medium text-tsubtle">Minimize</th>
								<th class="px-4 py-2"></th>
							</tr>
						</thead>
						<tbody class="divide-y divide-cbase">
							{#each criteria as criterion}
								<tr>
									<td class="px-4 py-2 text-tdefault">{criterion.name}</td>
									<td class="px-4 py-2 text-tbody text-xs">{criterion.input_type}</td>
									<td class="px-4 py-2">
										<AppCheckbox bind:checked={criterion.minimize} wrapperClass="" />
									</td>
									<td class="px-4 py-2">
										<button onclick={() => removeCriterion(criterion.attribute_name)} class="text-danger hover:text-danger/70 text-xs">✕</button>
									</td>
								</tr>
							{:else}
								<tr><td colspan="4" class="px-4 py-6 text-center text-tbody">No criteria selected.</td></tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>

			<!-- Pairwise comparison matrix (AHP) -->
			{#if method === "AHP" && criteria.length > 1}
				<div class="rounded-lg border border-cbase bg-secondary p-4">
					<p class="text-sm font-semibold text-tdefault mb-1">Pairwise Comparison Matrix</p>
					<p class="text-sm text-tsubtle mb-3">How much more important is the row criterion compared to the column criterion? (Saaty 1–9 scale)</p>
					<div class="overflow-x-auto">
						<table class="text-sm border-collapse">
							<thead>
								<tr>
									<th class="px-2 py-1"></th>
									{#each criteria.slice(1) as columnCriterion}
										<th class="px-3 py-1 text-center font-medium text-tsubtle whitespace-nowrap">{columnCriterion.name}</th>
									{/each}
								</tr>
							</thead>
							<tbody>
								{#each criteria.slice(0, -1) as rowCriterion, rowIndex}
									<tr>
										<td class="px-2 py-1 font-medium text-tdefault whitespace-nowrap pr-4">{rowCriterion.name}</td>
										{#each criteria as columnCriterion, columnIndex}
											{#if columnIndex > rowIndex}
												<td class="px-2 py-1">
													<select
														class="app-input py-1 text-xs"
														value={getPW(rowCriterion.attribute_name, columnCriterion.attribute_name)}
														onchange={(event) => setPW(rowCriterion.attribute_name, columnCriterion.attribute_name, Number(event.currentTarget.value))}
													>
														{#each SAATY_OPTIONS as saatyOption}
															<option value={saatyOption.value}>{saatyOption.label}</option>
														{/each}
													</select>
												</td>
											{:else if columnIndex < rowIndex}
												<td></td>
											{/if}
										{/each}
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			{/if}

			<!-- Direct weights (TOPSIS and ELECTRE II) -->
			{#if (method === "TOPSIS" || method === "ELECTRE2") && criteria.length > 0}
				<div class="rounded-lg border border-cbase bg-secondary p-4 space-y-3">
					<div>
						<p class="text-sm font-semibold text-tdefault">Criterion Weights</p>
						<p class="text-xs text-tsubtle mt-0.5">Enter relative importance for each criterion. Values are normalised automatically.</p>
					</div>
					<div class="space-y-2">
						{#each criteria as criterion}
							<div class="flex items-center gap-3">
								<span class="text-sm text-tdefault w-48 shrink-0">{criterion.name}</span>
								<AppInput
									type="number" min="0" step="0.1"
									value={getTW(criterion.attribute_name)}
									oninput={(event) => setTW(criterion.attribute_name, Math.max(0, Number(event.currentTarget.value)))}
									class="py-1 text-sm w-24"
									wrapperClass=""
								/>
								<span class="text-xs text-tsubtle w-12 text-right">
									{topsisTotal > 0 ? ((getTW(criterion.attribute_name) / topsisTotal) * 100).toFixed(1) : "0.0"}%
								</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}
		{/if}

		<!-- Alternatives -->
		<div>
			<div class="flex items-center justify-between mb-2">
				<h4 class="text-sm font-semibold text-tdefault">Alternatives</h4>
				<AppButton size="sm" variant="secondary" onclick={addRow}>Add Row</AppButton>
			</div>
			<div class="rounded-lg border border-cbase overflow-x-auto">
				<table class="w-full text-sm">
					<thead class="bg-secondary border-b border-cbase">
						<tr>
							<th class="px-3 py-2 text-left font-medium text-tsubtle">Name</th>
							<th class="px-3 py-2 text-left font-medium text-tsubtle">Machines</th>
							<th class="px-3 py-2 text-left font-medium text-tsubtle">Replacement (yrs)</th>
							{#each inputCriteria as criterion}
								<th class="px-3 py-2 text-left font-medium text-tsubtle">{criterion.name}</th>
							{/each}
							<th class="px-3 py-2"></th>
						</tr>
					</thead>
					<tbody class="divide-y divide-cbase">
						{#each alternatives as alternative, rowIndex}
							<tr>
								<td class="px-3 py-1.5"><AppInput class="py-1 text-sm w-24" bind:value={alternative.name} wrapperClass="" /></td>
								<td class="px-3 py-1.5"><AppInput type="number" class="py-1 text-sm w-20" bind:value={alternative.machine_number} wrapperClass="" /></td>
								<td class="px-3 py-1.5"><AppInput type="number" class="py-1 text-sm w-20" bind:value={alternative.replacement_period} wrapperClass="" /></td>
								{#each inputCriteria as criterion}
									<td class="px-3 py-1.5"><AppInput type="number" step="0.5" class="py-1 text-sm w-20" bind:value={alternative.scores[criterion.attribute_name]} wrapperClass="" /></td>
								{/each}
								<td class="px-3 py-1.5">
									<button onclick={() => removeRow(rowIndex)} class="text-danger hover:text-danger/70 text-xs">✕</button>
								</td>
							</tr>
						{:else}
							<tr><td colspan="99" class="px-4 py-6 text-center text-tbody">No alternatives yet.</td></tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	</div>

	{#snippet footer()}
		<AppButton onclick={save} loading={saving} disabled={!profileName.trim()}>Save</AppButton>
		<AppButton variant="secondary" onclick={() => (modalOpen = false)}>Cancel</AppButton>
	{/snippet}
</AppModal>
