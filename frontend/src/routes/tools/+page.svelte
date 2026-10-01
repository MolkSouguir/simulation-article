<script lang="ts">
	import { fmtNum } from "$lib/utils/format.js";
	import { costProfilesApi, machinesApi } from "$lib/api/index.js";
	import { AppButton, AppInput, AppModal, AppSelect } from "$lib/components/index.js";

	// Result of the Weibull fit for one machine model (one sheet of the Excel file)
	interface WeibullModelResult {
		model: string;
		n_machines: number;
		n_failures: number;
		n_tbf: number;
		beta: number | null;
		eta_days: number | null;
		eta_years: number | null;
		mean_mttr_hours: number | null;
		mean_cost_eur: number | null;
		warning: string | null;
	}

	let file = $state<File | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let results = $state<WeibullModelResult[]>([]);

	// "Create cost profile" modal, prefilled from a result row
	let costProfileModalOpen = $state(false);
	let costProfileSaving = $state(false);
	let costProfileForm = $state({ name: "", hourly_labor_cost: 60, corrective_maintenance_hours: 0, corrective_maintenance_additional_downtime_hours: 0, preventive_maintenance_hours: 0 });

	const openCostProfileModal = (row: WeibullModelResult) => {
		const mttr = row.mean_mttr_hours ?? 0;
		const cost = row.mean_cost_eur ?? 0;
		// Mean cost of a repair divided by its mean duration gives an hourly rate
		const derivedRate = mttr > 0 ? Math.round((cost / mttr) * 100) / 100 : 0;
		costProfileForm = {
			name: row.model,
			hourly_labor_cost: derivedRate,
			corrective_maintenance_hours: mttr,
			corrective_maintenance_additional_downtime_hours: 0,
			preventive_maintenance_hours: 0,
		};
		costProfileModalOpen = true;
	};

	const saveCostProfile = async () => {
		costProfileSaving = true;
		try {
			await costProfilesApi.create({
				name: costProfileForm.name,
				hourly_labor_cost: Number(costProfileForm.hourly_labor_cost),
				corrective_maintenance_hours: Number(costProfileForm.corrective_maintenance_hours),
				corrective_maintenance_additional_downtime_hours: Number(costProfileForm.corrective_maintenance_additional_downtime_hours),
				preventive_maintenance_hours: Number(costProfileForm.preventive_maintenance_hours),
			});
			costProfileModalOpen = false;
		} catch (saveError) {
			alert(String(saveError));
		} finally {
			costProfileSaving = false;
		}
	};

	// "Assign β/η" modal: applies a fitted result to every machine of one type
	let weibullModalOpen = $state(false);
	let weibullSaving = $state(false);
	let weibullRow = $state<WeibullModelResult | null>(null);
	let weibullMachineType = $state("ventilator");

	const openWeibullModal = (row: WeibullModelResult) => {
		weibullRow = row;
		weibullMachineType = "ventilator";
		weibullModalOpen = true;
	};

	const applyWeibull = async () => {
		if (!weibullRow || weibullRow.beta == null || weibullRow.eta_years == null) return;
		weibullSaving = true;
		try {
			const machines = await machinesApi.list();
			const targets = machines.filter((machine) => machine.machine_type === weibullMachineType);
			await Promise.all(
				targets.map((machine) => machinesApi.update(machine.id, { beta: weibullRow!.beta!, eta: weibullRow!.eta_years! }))
			);
			weibullModalOpen = false;
		} catch (applyError) {
			alert(String(applyError));
		} finally {
			weibullSaving = false;
		}
	};

	// Send the file to the backend and show one result row per machine model
	const runWeibullAnalysis = async () => {
		if (!file) return;
		loading = true;
		error = null;
		results = [];
		try {
			const formData = new FormData();
			formData.append("file", file);
			const response = await fetch("http://localhost:8000/api/tools/weibull-analysis", {
				method: "POST",
				body: formData,
			});
			if (!response.ok) {
				const text = await response.text();
				throw new Error(`${response.status} ${response.statusText}: ${text}`);
			}
			const data = await response.json();
			results = data.models;
		} catch (analysisError: unknown) {
			error = analysisError instanceof Error ? analysisError.message : String(analysisError);
		} finally {
			loading = false;
		}
	};
</script>

<div class="p-8 max-w-7xl mx-auto space-y-8">
	<div>
		<h2 class="text-xl font-semibold text-tdefault">Tools</h2>
		<p class="text-sm text-tsubtle mt-1">Reliability analysis utilities</p>
	</div>

	<div class="rounded-xl border border-cbase bg-card p-6 space-y-5">
		<div>
			<h3 class="text-base font-semibold text-tdefault">Weibull Analysis</h3>
			<p class="text-sm text-tsubtle mt-1 max-w-2xl">
				Upload an Excel (.xlsx / .xlsm) maintenance export — one sheet per machine model.
				The tool fits a 2-parameter Weibull distribution to the inter-failure times and
				returns β, η, mean MTTR, and mean corrective cost per model.
			</p>
		</div>

		<div class="flex items-center gap-3 flex-wrap">
			<label class="flex items-center gap-2 px-3 py-2 rounded-lg border border-cbase bg-secondary hover:bg-secondary/80 cursor-pointer text-sm text-tdefault transition-colors">
				<svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4 text-tsubtle" fill="none" viewBox="0 0 24 24" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a2 2 0 002 2h12a2 2 0 002-2v-1M12 12V4m0 0L8 8m4-4l4 4"/>
				</svg>
				{file ? file.name : "Choose file…"}
				<input
					type="file"
					accept=".xlsx,.xlsm"
					class="hidden"
					onchange={(event) => { file = event.currentTarget.files?.[0] ?? null; results = []; error = null; }}
				/>
			</label>

			<button
				onclick={runWeibullAnalysis}
				disabled={!file || loading}
				class="px-4 py-2 rounded-lg text-sm font-medium transition-colors
					{!file || loading ? 'bg-secondary text-tsubtle cursor-not-allowed' : 'bg-brand text-white hover:bg-brand/90'}"
			>
				{loading ? "Analysing…" : "Analyse"}
			</button>

			{#if results.length > 0}
				<span class="text-xs text-tsubtle">{results.length} model{results.length !== 1 ? "s" : ""} found</span>
			{/if}
		</div>

		{#if error}
			<div class="rounded-lg border border-danger bg-danger/10 px-4 py-3 text-sm text-danger whitespace-pre-wrap">{error}</div>
		{/if}

		{#if results.length > 0}
			<div class="rounded-lg border border-cbase overflow-x-auto">
				<table class="w-full text-sm">
					<thead class="bg-secondary border-b border-cbase">
						<tr>
							<th class="px-4 py-2.5 text-left font-medium text-tsubtle">Model</th>
							<th class="px-4 py-2.5 text-right font-medium text-tsubtle">Machines</th>
							<th class="px-4 py-2.5 text-right font-medium text-tsubtle">Failures</th>
							<th class="px-4 py-2.5 text-right font-medium text-tsubtle">TBF pts</th>
							<th class="px-4 py-2.5 text-right font-medium text-tsubtle">β (shape)</th>
							<th class="px-4 py-2.5 text-right font-medium text-tsubtle">η (days)</th>
							<th class="px-4 py-2.5 text-right font-medium text-tsubtle">η (years)</th>
							<th class="px-4 py-2.5 text-right font-medium text-tsubtle">Mean MTTR (h)</th>
							<th class="px-4 py-2.5 text-right font-medium text-tsubtle">Mean Cost (€)</th>
							<th class="px-4 py-2.5 text-left font-medium text-tsubtle">Note</th>
							<th class="px-4 py-2.5"></th>
						</tr>
					</thead>
					<tbody class="divide-y divide-cbase">
						{#each results as row}
							<tr class="hover:bg-secondary transition-colors">
								<td class="px-4 py-2.5 font-medium text-tdefault">{row.model}</td>
								<td class="px-4 py-2.5 text-right text-tbody">{row.n_machines}</td>
								<td class="px-4 py-2.5 text-right text-tbody">{row.n_failures}</td>
								<td class="px-4 py-2.5 text-right text-tbody">{row.n_tbf}</td>
								<td class="px-4 py-2.5 text-right font-mono text-tdefault">{fmtNum(row.beta, 4)}</td>
								<td class="px-4 py-2.5 text-right font-mono text-tdefault">{fmtNum(row.eta_days, 1)}</td>
								<td class="px-4 py-2.5 text-right font-mono text-tdefault">{fmtNum(row.eta_years, 4)}</td>
								<td class="px-4 py-2.5 text-right text-tbody">{fmtNum(row.mean_mttr_hours, 2)}</td>
								<td class="px-4 py-2.5 text-right text-tbody">{row.mean_cost_eur != null ? row.mean_cost_eur.toFixed(2) : "—"}</td>
								<td class="px-4 py-2.5 text-xs text-tsubtle italic">{row.warning ?? ""}</td>
								<td class="px-4 py-2.5">
									<div class="flex gap-1.5 justify-end">
										<AppButton variant="secondary" size="sm" onclick={() => openCostProfileModal(row)}>
											Create Cost Profile
										</AppButton>
										<AppButton variant="secondary" size="sm" onclick={() => openWeibullModal(row)} disabled={row.beta == null || row.eta_years == null}>
											Assign β/η
										</AppButton>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<div class="flex flex-wrap gap-x-6 gap-y-1 text-xs text-tsubtle pt-1">
				<span><span class="font-medium text-tdefault">β &gt; 1</span> — wear-out (increasing failure rate)</span>
				<span><span class="font-medium text-tdefault">β ≈ 1</span> — random failures (constant rate)</span>
				<span><span class="font-medium text-tdefault">β &lt; 1</span> — infant mortality</span>
				<span><span class="font-medium text-tdefault">η</span> — characteristic life (63.2 % of units fail by this time)</span>
			</div>
		{/if}
	</div>
</div>

<AppModal bind:open={costProfileModalOpen} title="Create Cost Profile" size="md">
	<AppInput label="Name" bind:value={costProfileForm.name} required />
	<AppInput label="Hourly Labor Cost (€/hr)" type="number" step="0.01" bind:value={costProfileForm.hourly_labor_cost} />
	<AppInput label="Corrective Maintenance Hours (labor)" type="number" step="0.01" bind:value={costProfileForm.corrective_maintenance_hours} />
	<AppInput label="Additional Downtime Hours (logistics, waiting, etc.)" type="number" step="0.1" bind:value={costProfileForm.corrective_maintenance_additional_downtime_hours} />
	<AppInput label="Preventive Maintenance Hours" type="number" step="0.1" bind:value={costProfileForm.preventive_maintenance_hours} />
	{#snippet footer()}
		<AppButton onclick={saveCostProfile} loading={costProfileSaving}>Create</AppButton>
		<AppButton variant="secondary" onclick={() => (costProfileModalOpen = false)}>Cancel</AppButton>
	{/snippet}
</AppModal>

<AppModal bind:open={weibullModalOpen} title="Assign β / η to Machines" size="sm">
	{#if weibullRow}
		<p class="text-sm text-tbody mb-4">
			Apply <span class="font-mono text-tdefault">β = {fmtNum(weibullRow.beta, 4)}</span>,
			<span class="font-mono text-tdefault">η = {fmtNum(weibullRow.eta_years, 4)} yr</span>
			to all machines of the selected type.
		</p>
	{/if}
	<AppSelect
		label="Machine Type"
		bind:value={weibullMachineType}
		items={[{ value: "ventilator", name: "Ventilator" }, { value: "dialysis", name: "Dialysis" }]}
	/>
	{#snippet footer()}
		<AppButton onclick={applyWeibull} loading={weibullSaving}>Apply</AppButton>
		<AppButton variant="secondary" onclick={() => (weibullModalOpen = false)}>Cancel</AppButton>
	{/snippet}
</AppModal>
