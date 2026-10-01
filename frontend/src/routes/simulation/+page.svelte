<script lang="ts">
	import { AppButton, AppInput, AppSelect, AppModal, AppCheckbox } from "$lib/components/index.js";
	import { api, API_BASE } from "$lib/api/client.js";
	import { scenarioProfilesApi, machineTypesApi, simulationRunsApi, DEFAULT_SIMULATION_BEHAVIOR, type ScenarioProfile, type MachineTypeRecord, type SimulationRun, type CostCiRankingSummary } from "$lib/api/index.js";
	import { fmtCell, fmtNum, pct, eur, fmtDateTime } from "$lib/utils/format.js";
	import { page } from "$app/state";
	import { goto, replaceState } from "$app/navigation";

	// Types

	interface CatalogEntry {
		attribute_name: string;
		name: string;
		input_type: "threshold_int" | "computed" | "qualitative" | "daily_hours";
		minimize: boolean;
	}

	// A criterion picked for this run (the user can switch minimize)
	interface SelectedCriterion extends CatalogEntry {
		minimize: boolean;
	}

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
	// AppSelect works with strings: String(1/3) is the same text for the option and the stored value
	const SAATY_ITEMS = SAATY_OPTIONS.map((saatyOption) => ({ value: String(saatyOption.value), name: saatyOption.label }));

	interface SimulationConfig {
		name: string;
		machine_number: number;
		replacement_period: number;
		scores: Record<string, number>;  // keyed by attribute_name
	}

	interface AlternativeResult {
		name: string;
		machine_number: number;
		replacement_period: number;
		total_cost: number;
		corrective_maintenance_cost: number;
		preventive_maintenance_cost: number;
		purchase_cost: number;
		normal_availability: number;
		crisis_availability: number;
		normal_hours_worked: number | null;
		normal_hours_scheduled: number | null;
		crisis_hours_worked: number | null;
		crisis_hours_scheduled: number | null;
		scores: Record<string, number>;
		final_score: number;
		rank: number;
	}

	interface CriterionWeight { name: string; attribute_name: string; weight: number; }

	// Reporting statistics (see analysis/statistics.py)
	interface MetricStats {
		mean: number | null;
		sd: number | null;
		se: number | null;
		ci_low: number | null;
		ci_high: number | null;
		half_width: number | null;
		rel_half_width: number | null;
		q_low: number | null;    // (1−c)/2 quantile of the replication values
		q_high: number | null;   // (1+c)/2 quantile of the replication values
		n_required: Record<string, number | null>;
		running_mean: number[];
		running_half_width: (number | null)[];
	}
	interface AlternativeStatistics { name: string; n: number; metrics: Record<string, MetricStats>; }
	interface BootstrapAlternative {
		name: string;
		rank_probabilities: number[];
		p_best: number;
		mean_rank: number;
		rank_ci: [number, number];
	}
	interface BootstrapSummary {
		samples: number;
		seed: number;
		method: string;
		replications_per_alternative: number;
		held_constant: string[];
		alternatives: BootstrapAlternative[];
	}

	interface RunResult {
		run_id: string | null;
		alternatives: AlternativeResult[];
		criteria_weights: CriterionWeight[];
		consistency_ratio: number;
		timeline_json: string | null;       // charts of the top-ranked alternative
		availability_json: string | null;
		chart_alternatives?: string[];      // alternatives whose charts the saved run can draw (missing on older runs)
		decision_matrix: Record<string, any>[];
		normalized_scores: Record<string, any>[];
		weighted_scores: Record<string, any>[];
		pairwise_matrix: Record<string, any>[];
		sensitivity_scores: Record<string, any>;
		sensitivity_ranks: Record<string, any>;
		confidence_level: number;
		statistics: AlternativeStatistics[];
		bootstrap: BootstrapSummary | null;
		cost_ci_ranking?: CostCiRankingSummary | null;   // missing on runs saved before it existed
		parameter_table: Record<string, any>;
	}

	// Loading a scenario profile

	let profileModalOpen = $state(false);
	let profiles = $state<ScenarioProfile[]>([]);
	let profilesLoading = $state(false);

	const openLoadProfile = async () => {
		profilesLoading = true;
		profileModalOpen = true;
		try { profiles = await scenarioProfilesApi.list(); }
		catch (loadError) { alert(String(loadError)); }
		finally { profilesLoading = false; }
	};

	let simBehavior = $state({ ...DEFAULT_SIMULATION_BEHAVIOR });
	// Name of the loaded profile (or reopened run). A new run is saved under this name in History.
	let loadedProfileName = $state("");

	const applyProfile = (profile: ScenarioProfile) => {
		selectedCriteria = profile.config.criteria.map((criterion) => ({ ...criterion }));
		configs = profile.config.alternatives.map((alternative) => ({ ...alternative, scores: { ...alternative.scores } }));
		const savedSimulation = Object.fromEntries(
			Object.entries(profile.config.simulation ?? {}).filter(([, value]) => value !== undefined)
		);
		simBehavior = { ...DEFAULT_SIMULATION_BEHAVIOR, ...savedSimulation };
		machineType = simBehavior.machine_type;
		decisionMethod = (profile.config.method ?? "AHP") as "AHP" | "TOPSIS" | "ELECTRE2";
		pairwiseValues = loadPairwiseFromTriangle(selectedCriteria, profile.config.pairwise_upper_triangle);
		const savedWeights = profile.config.direct_weights;
		if (savedWeights) {
			const weights: Record<string, number> = {};
			selectedCriteria.forEach((criterion, index) => { weights[criterion.attribute_name] = savedWeights[index] ?? 1; });
			topsisWeights = weights;
		}
		loadedProfileName = profile.name;
		profileModalOpen = false;
	};

	// Global parameters

	let simulationNumber = $state(10);
	let period = $state(15);
	let bootstrapSamples = $state(500);   // resamples for the ranking robustness (0 = off)
	const CONFIDENCE_LEVEL = 0.95;        // for the confidence intervals
	let parallel = $state(false);
	let maxWorkers = $state<number | null>(null);
	let baseYear = $state(new Date().getFullYear());
	// Random seed. It stays the same unless "Randomize" is ticked, so the same
	// inputs give the same results (and the same parameter table).
	let seed = $state(42);
	let randomizeSeed = $state(false);
	let lastSeedUsed = $state<number | null>(null);
	let machineType = $state("ventilator");
	let machineTypes = $state<MachineTypeRecord[]>([]);
	machineTypesApi.list().then((types) => {
		machineTypes = types;
		if (!machineType && types.length > 0) machineType = types[0].name;
	});
	let decisionMethod = $state<"AHP" | "TOPSIS" | "ELECTRE2">("AHP");

	const METHODS = [
		{ value: "AHP",      label: "AHP — Analytic Hierarchy Process" },
		{ value: "TOPSIS",   label: "TOPSIS" },
		{ value: "ELECTRE2", label: "ELECTRE II" },
	];

	// Criteria

	const CATALOG: CatalogEntry[] = [
		{ attribute_name: "normal_availability", name: "Available Machines — Normal",   input_type: "threshold_int", minimize: false },
		{ attribute_name: "crisis_availability", name: "Available Machines — Crisis",   input_type: "threshold_int", minimize: false },
		{ attribute_name: "normal_hours_availability", name: "Availability — Normal",   input_type: "daily_hours",   minimize: false },
		{ attribute_name: "crisis_hours_availability", name: "Availability — Crisis",   input_type: "daily_hours",   minimize: false },
		{ attribute_name: "total_cost",          name: "Total Cost",              input_type: "computed",      minimize: true  },
		{ attribute_name: "staff_satisfaction",  name: "Staff Satisfaction",      input_type: "qualitative",   minimize: false },
		{ attribute_name: "clinical_features",   name: "Sensitivity to Obsolescence",          input_type: "qualitative", minimize: false },
		{ attribute_name: "logistics_procurement", name: "Easiness of Logistics & Procurement", input_type: "qualitative", minimize: false },
	];

	let selectedCriteria = $state<SelectedCriterion[]>([]);

	// TOPSIS / ELECTRE II weights, keyed by attribute_name
	let topsisWeights = $state<Record<string, number>>({});
	const getTW = (attribute: string) => topsisWeights[attribute] ?? 1;
	const setTW = (attribute: string, weight: number) => { topsisWeights = { ...topsisWeights, [attribute]: weight }; };
	const buildDirectWeights = (criteriaList: SelectedCriterion[]) => criteriaList.map((criterion) => getTW(criterion.attribute_name));

	// AHP comparisons, upper triangle only, keyed by "rowAttribute:columnAttribute"
	let pairwiseValues = $state<Record<string, number>>({});

	const pwKey = (rowAttribute: string, columnAttribute: string) => `${rowAttribute}:${columnAttribute}`;
	const getPW = (rowAttribute: string, columnAttribute: string) => pairwiseValues[pwKey(rowAttribute, columnAttribute)] ?? 1;
	const setPW = (rowAttribute: string, columnAttribute: string, value: number) => {
		pairwiseValues = { ...pairwiseValues, [pwKey(rowAttribute, columnAttribute)]: value };
	};
	const buildUpperTriangle = (criteriaList: SelectedCriterion[]) => {
		const triangle: number[] = [];
		for (let row = 0; row < criteriaList.length; row++)
			for (let column = row + 1; column < criteriaList.length; column++)
				triangle.push(getPW(criteriaList[row].attribute_name, criteriaList[column].attribute_name));
		return triangle;
	};
	const loadPairwiseFromTriangle = (criteriaList: SelectedCriterion[], triangle: number[] | undefined) => {
		const values: Record<string, number> = {};
		if (!triangle) return values;
		let triangleIndex = 0;
		for (let row = 0; row < criteriaList.length; row++)
			for (let column = row + 1; column < criteriaList.length; column++)
				values[pwKey(criteriaList[row].attribute_name, criteriaList[column].attribute_name)] = triangle[triangleIndex++] ?? 1;
		return values;
	};

	// Criteria not picked yet
	const availableCatalog = $derived(
		CATALOG.filter((entry) => !selectedCriteria.some((selected) => selected.attribute_name === entry.attribute_name))
	);

	let criteriaToAdd = $state("");

	const addCriterion = () => {
		const entry = CATALOG.find((catalogEntry) => catalogEntry.attribute_name === criteriaToAdd);
		if (!entry) return;
		selectedCriteria = [...selectedCriteria, { ...entry }];
		criteriaToAdd = "";
	};

	const removeCriterion = (attribute: string) => {
		selectedCriteria = selectedCriteria.filter((criterion) => criterion.attribute_name !== attribute);
		// Drop its score from every alternative too
		configs = configs.map((config) => {
			const { [attribute]: _, ...remainingScores } = config.scores;
			return { ...config, scores: remainingScores };
		});
	};

	// Criteria that need a value per alternative. They become the columns of the alternatives table
	const inputCriteria = $derived(
		selectedCriteria.filter((criterion) => criterion.input_type !== "computed")
	);

	const hasCriterion = (attribute: string) => selectedCriteria.some((criterion) => criterion.attribute_name === attribute);
	const showNormalAvail = $derived(hasCriterion("normal_availability"));
	const showCrisisAvail = $derived(hasCriterion("crisis_availability"));
	const showAvailTab = $derived(showNormalAvail || showCrisisAvail);
	const showNormalHours = $derived(hasCriterion("normal_hours_availability"));
	const showCrisisHours = $derived(hasCriterion("crisis_hours_availability"));

	// Alternatives table

	const makeDefaultScores = (): Record<string, number> => {
		const scores: Record<string, number> = {};
		for (const criterion of inputCriteria) {
			scores[criterion.attribute_name] = criterion.input_type === "threshold_int" ? 36 : criterion.input_type === "daily_hours" ? 24 : 0;
		}
		return scores;
	};

	let configs = $state<SimulationConfig[]>([]);

	// A new row copies the previous one, so similar alternatives are quick to enter
	const addRow = () => {
		const last = configs[configs.length - 1];
		configs = [...configs, {
			name: `Alt-${configs.length + 1}`,
			machine_number: last?.machine_number ?? 38,
			replacement_period: last?.replacement_period ?? 7,
			scores: last ? { ...last.scores } : makeDefaultScores(),
		}];
	};

	const removeRow = (rowIndex: number) => {
		configs = configs.filter((_, index) => index !== rowIndex);
	};

	// Running a simulation

	let running = $state(false);
	let result = $state<RunResult | null>(null);
	let runError = $state<string | null>(null);
	type TabId = "ranking" | "timeline" | "availability" | "ahp" | "sensitivity" | "statistics";
	let activeTab = $state<TabId>("ranking");
	const TABS: { id: TabId; label: string }[] = [
		{ id: "ranking", label: "Ranking" },
		{ id: "timeline", label: "Event Timeline" },
		{ id: "availability", label: "Machines Available" },
		{ id: "ahp", label: "AHP Details" },
		{ id: "sensitivity", label: "Sensitivity" },
		{ id: "statistics", label: "Statistics & Report" },
	];

	const visibleTabs = $derived(TABS.filter((tab) => tab.id !== "availability" || showAvailTab));

	// The saved run the result on screen belongs to. `reopened` means it was
	// opened from History rather than run just now.
	let savedRun = $state<{ id: string; name: string; created_at: string; reopened: boolean } | null>(null);
	let loadingRun = $state(false);

	const run = async () => {
		running = true;
		result = null;
		savedRun = null;
		runError = null;
		activeTab = "ranking";
		const seedUsed = randomizeSeed ? Math.floor(Math.random() * 1_000_000) : Number(seed);
		try {
			result = await api.post<RunResult>("/simulation/run", {
				configurations: configs.map((config) => ({
					...config,
					machine_type: machineType,
					session_days: simBehavior.session_days,
					shift_durations: simBehavior.shift_durations,
				})),
				method: decisionMethod,
				criteria_config: selectedCriteria.map((criterion) => ({
					attribute_name: criterion.attribute_name,
					name: criterion.name,
					minimize: criterion.minimize,
					input_type: criterion.input_type,
				})),
				pairwise_upper_triangle: decisionMethod === "AHP" ? buildUpperTriangle(selectedCriteria) : [],
				direct_weights: (decisionMethod === "TOPSIS" || decisionMethod === "ELECTRE2") ? buildDirectWeights(selectedCriteria) : [],
				simulation_number: simulationNumber,
				period,
				base_year: baseYear,
				seed: seedUsed,
				parallel,
				max_workers: parallel ? maxWorkers : null,
				name: loadedProfileName,
				confidence_level: CONFIDENCE_LEVEL,
				bootstrap_samples: bootstrapSamples,
			});
			lastSeedUsed = seedUsed;
			statAlt = result?.alternatives[0]?.name ?? "";
			resetCharts();
			if (result?.run_id) {
				savedRun = {
					id: result.run_id,
					name: loadedProfileName.trim() || `${decisionMethod} — ${machineType}`,
					created_at: new Date().toISOString(),
					reopened: false,
				};
				// Point the address at the saved run, so a refresh reopens it
				replaceState(`/simulation?run=${result.run_id}`, {});
			}
		} catch (requestError) {
			runError = String(requestError);
		} finally {
			running = false;
		}
	};

	// Reopening a saved run (History page, /simulation?run=<id>). The inputs
	// are put back exactly as they were sent, so the run can be changed and run
	// again, and the stored result is shown without simulating anything.

	const restoreRun = (savedRunRecord: SimulationRun) => {
		const request = savedRunRecord.request;
		selectedCriteria = (request.criteria_config ?? []).map((criterion: SelectedCriterion) => ({ ...criterion }));
		configs = (request.configurations ?? []).map((config: Record<string, any>) => ({
			name: config.name,
			machine_number: config.machine_number,
			replacement_period: config.replacement_period,
			scores: { ...config.scores },
		}));
		const firstConfig = request.configurations?.[0];
		if (firstConfig) {
			machineType = firstConfig.machine_type;
			simBehavior = {
				...DEFAULT_SIMULATION_BEHAVIOR,
				machine_type: firstConfig.machine_type,
				session_days: firstConfig.session_days,
				shift_durations: firstConfig.shift_durations,
			};
		}
		decisionMethod = (request.method ?? "AHP") as "AHP" | "TOPSIS" | "ELECTRE2";
		pairwiseValues = loadPairwiseFromTriangle(selectedCriteria, request.pairwise_upper_triangle);
		if (request.direct_weights?.length) {
			const weights: Record<string, number> = {};
			selectedCriteria.forEach((criterion, index) => { weights[criterion.attribute_name] = request.direct_weights[index] ?? 1; });
			topsisWeights = weights;
		}
		simulationNumber = request.simulation_number ?? simulationNumber;
		period = request.period ?? period;
		bootstrapSamples = request.bootstrap_samples ?? bootstrapSamples;
		baseYear = request.base_year || baseYear;
		seed = request.seed ?? seed;
		randomizeSeed = false;
		parallel = request.parallel ?? false;
		maxWorkers = request.max_workers ?? null;
		loadedProfileName = savedRunRecord.name;

		result = { ...(savedRunRecord.result as RunResult), run_id: savedRunRecord.id };
		lastSeedUsed = request.seed ?? null;
		statAlt = result.alternatives[0]?.name ?? "";
		resetCharts();
		activeTab = "ranking";
		savedRun = { id: savedRunRecord.id, name: savedRunRecord.name, created_at: savedRunRecord.created_at, reopened: true };
	};

	const loadSavedRun = async (runId: string) => {
		loadingRun = true;
		runError = null;
		try { restoreRun(await simulationRunsApi.get(runId)); }
		catch (loadError) { runError = String(loadError); }
		finally { loadingRun = false; }
	};

	// PDF of the saved run (inputs and every tab except the timeline and availability charts)
	let exportingPdf = $state(false);
	const exportPdf = async () => {
		if (!savedRun) return;
		exportingPdf = true;
		try { await simulationRunsApi.downloadPdf(savedRun.id); }
		catch (exportError) { alert(String(exportError)); }
		finally { exportingPdf = false; }
	};

	const runParam = page.url.searchParams.get("run");
	if (runParam) loadSavedRun(runParam);

	// Statistics & report

	// Same keys as METRICS in analysis/statistics.py. `kind` decides the formatting and the chart unit.
	type MetricKind = "eur" | "fraction" | "units";
	const METRIC_DEFS: Record<string, { label: string; kind: MetricKind }> = {
		total_cost:                  { label: "Total cost",                     kind: "eur" },
		purchase_cost:               { label: "Purchase cost",                  kind: "eur" },
		corrective_maintenance_cost: { label: "CM cost",                        kind: "eur" },
		preventive_maintenance_cost: { label: "PM cost",                        kind: "eur" },
		normal_availability:         { label: "Availability — normal",          kind: "fraction" },
		crisis_availability:         { label: "Availability — crisis",          kind: "fraction" },
		crisis_expected_unmet:       { label: "Expected unmet demand — crisis", kind: "units" },
	};
	const METRIC_KEYS = Object.keys(METRIC_DEFS);
	// Expected unmet demand has its own column in the Resilience table instead
	const UNCERTAINTY_KEYS = METRIC_KEYS.filter((metric) => metric !== "crisis_expected_unmet");
	const metricLabel = (metric: string): string => METRIC_DEFS[metric].label;
	const REL_HW_FLAG = 0.05;   // convergence is flagged above this relative half-width

	let statMetric = $state("total_cost");
	let statAlt = $state("");
	let downloadingReport = $state(false);
	let convMeanEl = $state<HTMLDivElement | null>(null);
	let convRelEl = $state<HTMLDivElement | null>(null);

	const statsByName = $derived(new Map((result?.statistics ?? []).map((alternativeStats) => [alternativeStats.name, alternativeStats])));
	// Replications per alternative in the result. With a single one there is no spread to
	// measure, so no confidence intervals, convergence or ranking robustness.
	const replicationCount = $derived(result?.statistics[0]?.n ?? 0);
	const hasSpread = $derived(replicationCount >= 2);

	const fmtMetric = (metric: string, value: number | null | undefined): string => {
		if (value == null) return "—";
		switch (METRIC_DEFS[metric].kind) {
			case "eur": return eur(value);
			case "fraction": return `${fmtNum(value * 100, 3)}%`;
			case "units": return fmtNum(value, 3);
		}
	};
	/** Confidence half-width: euros for costs, percentage points for fractions, units otherwise. */
	const fmtHw = (metric: string, value: number | null | undefined): string => {
		if (value == null) return "—";
		switch (METRIC_DEFS[metric].kind) {
			case "eur": return `± ${eur(value)}`;
			case "fraction": return `± ${fmtNum(value * 100, 3)} pp`;
			case "units": return `± ${fmtNum(value, 3)}`;
		}
	};
	const UNIT_SUFFIX: Record<MetricKind, string> = { eur: "€", fraction: "%", units: "units" };
	const fmtRel = (value: number | null | undefined): string => (value == null ? "—" : `${(value * 100).toFixed(2)}%`);
	const ciLabel = $derived(`${Math.round((result?.confidence_level ?? CONFIDENCE_LEVEL) * 100)}% CI`);

	// Ranks with every total cost anywhere in its confidence interval (Sensitivity tab)
	const costCiRanking = $derived(result?.cost_ci_ranking ?? null);
	const rankRangeText = (best: number, worst: number): string => (best === worst ? `${best} (stable)` : `${best}–${worst}`);
	let costCiChartEl = $state<HTMLDivElement | null>(null);

	const bootstrapSorted = $derived(
		[...(result?.bootstrap?.alternatives ?? [])].sort((alternativeA, alternativeB) => alternativeA.mean_rank - alternativeB.mean_rank)
	);
	/** Shading of a rank-probability cell: the more likely, the darker. */
	const rankCellClass = (probability: number): string =>
		probability <= 0 ? "text-tsubtle"
		: probability < 0.25 ? "bg-brand/10 text-tdefault"
		: probability < 0.5 ? "bg-brand/25 text-tdefault"
		: probability < 0.75 ? "bg-brand/45 text-tdefault"
		: "bg-brand/70 text-white font-medium";

	const downloadReport = async () => {
		if (!result) return;
		downloadingReport = true;
		try {
			// The workbook doesn't need the chart data, so leave it out of the request
			const { timeline_json, availability_json, sensitivity_scores, sensitivity_ranks, ...payload } = result;
			const response = await fetch(`${API_BASE}/simulation/report`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(payload),
			});
			if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
			const blob = await response.blob();
			const url = URL.createObjectURL(blob);
			const downloadLink = document.createElement("a");
			downloadLink.href = url;
			downloadLink.download = "simulation_report.xlsx";
			downloadLink.click();
			URL.revokeObjectURL(url);
		} catch (downloadError) {
			alert(String(downloadError));
		} finally {
			downloadingReport = false;
		}
	};

	/** Text of one cell of the parameter tables. */
	const cellText = (value: unknown): string => {
		if (value == null) return "—";
		if (Array.isArray(value)) return value.map(cellText).join(", ");
		if (typeof value === "object") {
			return Object.entries(value as Record<string, unknown>).map(([key, item]) => `${key}: ${cellText(item)}`).join("; ");
		}
		if (typeof value === "boolean") return value ? "yes" : "no";
		if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(4).replace(/\.?0+$/, "");
		return String(value);
	};
	const rowKeys = (rows: Record<string, unknown>[]): string[] =>
		rows.length ? Object.keys(rows[0]) : [];

	// The nested parameter-table sections, flattened into rows for display
	const paramAlternativeRows = $derived.by(() => {
		const rows = (result?.parameter_table?.alternatives ?? []) as Record<string, any>[];
		return rows.map((alternative) => ({
			name: alternative.name, machine_type: alternative.machine_type, N: alternative.machine_number, T: alternative.replacement_period,
			normal_threshold: alternative.normal_threshold, crisis_threshold: alternative.crisis_threshold, standby_pool: alternative.standby_pool,
			session_days: alternative.session_days, shift_durations: alternative.shift_durations,
			cohorts_simulated: (alternative.cohorts_used ?? [])
				.map((cohort: any) => `${cohort.purchase_year}×${cohort.count} @ ${cohort.purchase_cost}`)
				.join("; "),
			...Object.fromEntries(Object.entries(alternative.scores ?? {}).map(([attribute, score]) => [`score: ${attribute}`, score])),
		}));
	});
	const paramPmRows = $derived.by(() => {
		const programmes = (result?.parameter_table?.pm_programmes ?? []) as Record<string, any>[];
		return programmes.flatMap((programme) => (programme.cycle_years ?? []).map((cycleYear: any) => ({
			programme: programme.name, interval_years: programme.years_interval, cycle_length_years: programme.cycle_length_years,
			cycle_year: cycleYear.order, pm_hours: cycleYear.preventive_maintenance_hours, hourly_labor_cost: cycleYear.hourly_labor_cost,
			pm_year_cost: cycleYear.pm_year_cost, parts_replaced: cycleYear.parts_replaced?.length ? cycleYear.parts_replaced : "—",
		})));
	});

	// Charts (Plotly is loaded only when a chart is shown)

	const CHART_COLORS = ["#1f77b4","#d62728","#2ca02c","#ff7f0e","#9467bd",
		"#8c564b","#e377c2","#7f7f7f","#bcbd22","#17becf","#0e4c92","#a01f1f"];

	let timelineEl = $state<HTMLDivElement | null>(null);
	let availabilityEl = $state<HTMLDivElement | null>(null);

	// Timeline and availability show one alternative at a time. The run returns
	// the charts of the top-ranked one, and the others are drawn by the API from the
	// saved run when picked, and kept here so switching back is instant.
	type AlternativeCharts = { timeline_json: string | null; availability_json: string | null };
	let chartAlt = $state("");
	let chartCache = $state<Record<string, AlternativeCharts>>({});
	let chartLoading = $state(false);
	let chartError = $state<string | null>(null);

	const chartAlternatives = $derived(result?.run_id ? (result.chart_alternatives ?? []) : []);
	const currentCharts = $derived<AlternativeCharts | null>(
		chartCache[chartAlt] ?? (chartAlternatives.length ? null : result)
	);

	const resetCharts = () => {
		chartAlt = result?.alternatives[0]?.name ?? "";
		chartError = null;
		chartCache = result?.timeline_json || result?.availability_json
			? { [chartAlt]: { timeline_json: result.timeline_json, availability_json: result.availability_json } }
			: {};
	};

	const loadCharts = async (runId: string, alternativeName: string) => {
		chartLoading = true;
		chartError = null;
		try {
			const charts = await simulationRunsApi.charts(runId, alternativeName);
			chartCache = { ...chartCache, [alternativeName]: charts };
		} catch (loadError) {
			chartError = String(loadError);
		} finally {
			chartLoading = false;
		}
	};

	$effect(() => {
		if ((activeTab === "timeline" || activeTab === "availability") && result?.run_id
			&& chartAlternatives.includes(chartAlt) && !chartCache[chartAlt] && !chartLoading && !chartError) {
			loadCharts(result.run_id, chartAlt);
		}
	});
	let sensitivityRankEls = $state<Record<string, HTMLDivElement>>({});

	// Every chart on this page: Times New Roman, with axis text large enough to read when the
	// page is zoomed out. The fonts are set explicitly so they also override the template
	// inside the server-built timeline and availability figures.
	const CHART_FONT_FAMILY = '"Times New Roman", Times, serif';
	const withChartFonts = (layout: Record<string, any>): Record<string, any> => {
		const font = (existing: Record<string, any> | undefined, size: number) => ({ ...existing, family: CHART_FONT_FAMILY, size });
		const styled: Record<string, any> = {
			...layout,
			font: font(layout.font, 18),
			title: { ...(typeof layout.title === "string" ? { text: layout.title } : layout.title), font: font(layout.title?.font, 22) },
			legend: { ...layout.legend, font: font(layout.legend?.font, 16) },
			hoverlabel: { ...layout.hoverlabel, font: font(layout.hoverlabel?.font, 16) },
		};
		// Every axis, including extra ones (xaxis2, yaxis2, ...)
		for (const key of Object.keys(layout).filter((layoutKey) => /^[xy]axis\d*$/.test(layoutKey))) {
			const axis = layout[key] ?? {};
			const axisTitle = typeof axis.title === "string" ? { text: axis.title } : axis.title;
			styled[key] = { ...axis, tickfont: font(axis.tickfont, 18), title: { ...axisTitle, font: font(axisTitle?.font, 20) } };
		}
		return styled;
	};
	const plotWithFonts = (plotly: any, element: HTMLDivElement, data: any[], layout: Record<string, any>, config?: Record<string, any>) =>
		plotly.newPlot(element, data, withChartFonts(layout), config);

	const renderPlotly = async (element: HTMLDivElement, json: string) => {
		const Plotly = (await import("plotly.js-dist-min")).default;
		const figure = JSON.parse(json);
		plotWithFonts(Plotly, element, figure.data, { ...figure.layout, responsive: true });
	};

	$effect(() => {
		if (activeTab === "timeline" && currentCharts?.timeline_json && timelineEl) {
			renderPlotly(timelineEl, currentCharts.timeline_json);
		}
	});

	$effect(() => {
		if (activeTab === "availability" && currentCharts?.availability_json && availabilityEl) {
			renderPlotly(availabilityEl, currentCharts.availability_json);
		}
	});

	// The availability criteria are called service rates in the sensitivity charts
	const SERVICE_RATE_LABELS: Record<string, string> = {
		normal_availability: "Service Rate — Normal",
		crisis_availability: "Service Rate — Crisis",
	};
	const chartCriterionLabel = (criterionName: string): string => {
		const attribute = result?.criteria_weights.find((criterionWeight) => criterionWeight.name === criterionName)?.attribute_name;
		return (attribute && SERVICE_RATE_LABELS[attribute]) || criterionName;
	};

	// One rank chart per criterion. Plotly 3 only reads titles written as { text }.
	$effect(() => {
		if (activeTab === "sensitivity" && result?.sensitivity_ranks) {
			const criteriaNames = Object.keys(result.sensitivity_ranks);
			criteriaNames.forEach(async (criterion) => {
				const rankEl = sensitivityRankEls[criterion];
				if (!rankEl) return;

				const Plotly = (await import("plotly.js-dist-min")).default;
				const ranksData = result!.sensitivity_ranks[criterion];
				const weights = ranksData.weights;
				const alternativeNames = Object.keys(ranksData).filter((key) => key !== "weights");
				const label = chartCriterionLabel(criterion);

				plotWithFonts(Plotly, rankEl, alternativeNames.map((name, index) => ({
					x: weights, y: ranksData[name],
					mode: "lines+markers", name,
					line: { color: CHART_COLORS[index % CHART_COLORS.length], width: 2 },
					marker: { size: 4 },
				})), {
					title: { text: `Rank Sensitivity: ${label}` },
					xaxis: { title: { text: `Weight of "${label}"` } },
					yaxis: { title: { text: "Rank" }, autorange: "reversed", dtick: 1 },
					height: 34 * alternativeNames.length + 170,   // same as the rank range chart
					responsive: true,
					plot_bgcolor: "white",
				});
			});
		}
	});

	// Rank range chart: every alternative at its rank with the mean costs, and for the
	// ones that can switch, an arrow to each rank they reach with the costs in their CI.
	// Only the switching ones are coloured; the rank rows carry the names.
	const RANK_SWITCH_COLOR = "#1447E6";   // brand
	const RANK_STABLE_COLOR = "#6A7282";   // subtle text grey
	$effect(() => {
		if (activeTab !== "sensitivity" || !costCiRanking || !costCiChartEl) return;
		const element = costCiChartEl;
		const entries = [...costCiRanking.alternatives].sort((first, second) => first.rank_base - second.rank_base);
		const label = ciLabel;
		const canSwitch = (entry: (typeof entries)[number]) => entry.rank_best !== entry.rank_worst;
		(async () => {
			const Plotly = (await import("plotly.js-dist-min")).default;
			const rowOf = new Map(entries.map((entry, row) => [entry.name, row]));
			const markers = (group: typeof entries, name: string, color: string) => ({
				type: "scatter", mode: "markers", name,
				x: group.map((entry) => entry.rank_base),
				y: group.map((entry) => rowOf.get(entry.name)),
				text: group.map((entry) => entry.name),
				customdata: group.map((entry) => rankRangeText(entry.rank_best, entry.rank_worst)),
				hovertemplate: `%{text}: rank %{x}<br>With the costs in their ${label}: %{customdata}<extra></extra>`,
				marker: { color, size: 11, line: { color: "white", width: 2 } },
			});
			const arrows = entries.filter(canSwitch).flatMap((entry) =>
				[...new Set([entry.rank_best, entry.rank_worst])]
					.filter((rank) => rank !== entry.rank_base)
					.map((rank) => ({
						x: rank, y: rowOf.get(entry.name), ax: entry.rank_base, ay: rowOf.get(entry.name),
						xref: "x", yref: "y", axref: "x", ayref: "y", text: "",
						showarrow: true, arrowhead: 2, arrowsize: 1.3, arrowwidth: 2, arrowcolor: RANK_SWITCH_COLOR, startstandoff: 7,
					}))
			);
			plotWithFonts(Plotly, element, [
				markers(entries.filter((entry) => !canSwitch(entry)), "Rank holds", RANK_STABLE_COLOR),
				markers(entries.filter(canSwitch), "Rank switches", RANK_SWITCH_COLOR),
			], {
				title: { text: `Rank range with total costs in their ${label}` },
				xaxis: { title: { text: "Ranks" }, dtick: 1, range: [0.5, entries.length + 0.5], zeroline: false, gridcolor: "#E5E7EB" },
				yaxis: {
					tickvals: entries.map((_, row) => row), ticktext: entries.map((entry) => entry.name),
					range: [entries.length - 0.5, -0.5], zeroline: false, gridcolor: "#E5E7EB",
				},
				annotations: arrows,
				showlegend: true,
				legend: { orientation: "h", x: 0, y: -0.22, yanchor: "top" },
				height: 34 * entries.length + 170,
				margin: { t: 60, r: 20, b: 140, l: 80 },
				plot_bgcolor: "white",
			}, { responsive: true, displaylogo: false });
		})();
	});

	// Convergence charts: the running mean with its confidence band for one
	// alternative, and the relative half-width against the number of runs for all.
	$effect(() => {
		if (activeTab !== "statistics" || !result?.statistics.length || !convMeanEl || !convRelEl) return;
		const metric = statMetric;
		const label = metricLabel(metric);
		const kind = METRIC_DEFS[metric].kind;
		const scale = kind === "fraction" ? 100 : 1;
		const yTitle = `${label} (${UNIT_SUFFIX[kind]})`;
		const allStats = result.statistics;
		const chosen = statsByName.get(statAlt) ?? allStats[0];
		const meanEl = convMeanEl;
		const relEl = convRelEl;

		(async () => {
			const Plotly = (await import("plotly.js-dist-min")).default;

			const chosenMetric = chosen.metrics[metric];
			const replicationNumbers = chosenMetric.running_mean.map((_, index) => index + 1);
			const mean = chosenMetric.running_mean.map((value) => value * scale);
			const upper = chosenMetric.running_mean.map((value, index) => (value + (chosenMetric.running_half_width[index] ?? 0)) * scale);
			const lower = chosenMetric.running_mean.map((value, index) => (value - (chosenMetric.running_half_width[index] ?? 0)) * scale);
			plotWithFonts(Plotly, meanEl, [
				{ x: replicationNumbers, y: upper, mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
				{ x: replicationNumbers, y: lower, mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: "rgba(31,119,180,0.18)", name: ciLabel },
				{ x: replicationNumbers, y: mean, mode: "lines+markers", line: { color: "#1f77b4", width: 2 }, marker: { size: 4 }, name: "Running mean" },
			], {
				title: { text: `Running mean — ${chosen.name} — ${label}` },
				xaxis: { title: { text: "Replications" } },
				yaxis: { title: { text: yTitle } },
				plot_bgcolor: "white", responsive: true, legend: { orientation: "h", y: -0.32 }, margin: { b: 120 },
			});

			const traces = allStats.map((alternativeStats, alternativeIndex) => {
				const metricStats = alternativeStats.metrics[metric];
				return {
					x: metricStats.running_mean.map((_, index) => index + 1),
					y: metricStats.running_mean.map((value, index) => {
						const halfWidth = metricStats.running_half_width[index];
						return halfWidth == null || value === 0 ? null : (halfWidth / Math.abs(value)) * 100;
					}),
					mode: "lines", name: alternativeStats.name,
					line: { color: CHART_COLORS[alternativeIndex % CHART_COLORS.length], width: 2 },
				};
			});
			const maxReplications = Math.max(...allStats.map((alternativeStats) => alternativeStats.n));
			plotWithFonts(Plotly, relEl, traces, {
				title: { text: `Relative ${ciLabel} half-width — ${label}` },
				xaxis: { title: { text: "Replications" } },
				yaxis: { title: { text: "Half-width / mean (%)" }, rangemode: "tozero" },
				shapes: [{ type: "line", x0: 1, x1: maxReplications, y0: REL_HW_FLAG * 100, y1: REL_HW_FLAG * 100,
					line: { color: "#d62728", dash: "dash", width: 1 } }],
				annotations: [{ x: maxReplications, y: REL_HW_FLAG * 100, text: `${REL_HW_FLAG * 100}% target`, showarrow: false,
					xanchor: "right", yanchor: "bottom", font: { color: "#d62728", size: 16 } }],
				plot_bgcolor: "white", responsive: true,
			});
		})();
	});

	// Helpers

	const hoursRatio = (worked: number | null, scheduled: number | null): string =>
		scheduled == null || worked == null || scheduled === 0 ? "—" : String(worked / scheduled);

	const matrixColumns = (rows: Record<string, any>[]) => {
		if (!rows.length) return [];
		return Object.keys(rows[0]).filter((key) => key !== "_row");
	};
</script>

<div class="p-6 space-y-6">

	<!-- Header -->
	<div class="flex items-start justify-between">
		<div>
			<h2 class="text-xl font-semibold text-theading">Simulation & AHP Analysis</h2>
			<p class="text-sm text-tbody">Configure alternatives, run Monte Carlo simulations, rank with AHP</p>
		</div>
		<AppButton variant="secondary" onclick={openLoadProfile}>Load Profile</AppButton>
	</div>

	<!-- Parameters -->
	<div class="rounded-lg border border-cbase p-4 bg-secondary">
		<h3 class="text-sm font-medium text-tdefault mb-3">Global Parameters</h3>
		<div class="flex flex-wrap gap-x-6 gap-y-4 items-end">
			<AppInput label="Monte Carlo runs" type="number" bind:value={simulationNumber} min="1" wrapperClass="w-48" />
			<AppInput label="Simulation horizon (years)" type="number" bind:value={period} min="1" wrapperClass="w-48" />
			<AppInput label="Bootstrap draws (ranks)" type="number" bind:value={bootstrapSamples} min="0" max="20000" step="100" wrapperClass="w-44" title="Resamples of the replications used to estimate rank probabilities. 0 disables." />
			<AppInput label="Base year" type="number" bind:value={baseYear} min="2000" max="2100" wrapperClass="w-36" />
			<div class="flex flex-col gap-1">
				<AppCheckbox label="Randomize seed" bind:checked={randomizeSeed} wrapperClass="mb-0" />
				<AppInput
					label="Random seed"
					type="number"
					bind:value={seed}
					min="0"
					step="1"
					wrapperClass="w-36 mb-0"
					disabled={randomizeSeed}
					title="Seeds the simulation RNG and the bootstrap. Same seed + same inputs = same results."
				/>
			</div>
			<AppSelect
				label="Machine type"
				bind:value={machineType}
				items={machineTypes.map((machineTypeRecord) => ({ value: machineTypeRecord.name, name: machineTypeRecord.name }))}
				wrapperClass="w-48"
			/>
			<div class="flex flex-col gap-1">
				<AppCheckbox label="Run in parallel" bind:checked={parallel} wrapperClass="mb-0" />
				<AppInput
					label="Worker processes"
					type="number"
					bind:value={maxWorkers}
					min="1"
					placeholder="auto"
					wrapperClass="w-36 mb-0"
					disabled={!parallel}
				/>
			</div>
			<AppButton onclick={run} loading={running} disabled={configs.length === 0}>
				{running ? "Running…" : "Run Simulation"}
			</AppButton>
		</div>
		{#if running}
			<p class="text-xs text-tsubtle mt-3">
				Running {simulationNumber} Monte Carlo run{simulationNumber !== 1 ? "s" : ""} × {configs.length} alternative{configs.length !== 1 ? "s" : ""}. This may take a few minutes…
			</p>
		{/if}
	</div>

	<!-- Criteria editor -->
	<div>
		<div class="flex items-center justify-between mb-2">
			<h3 class="text-sm font-medium text-tdefault">Criteria</h3>
			<div class="flex items-center gap-3">
				<AppSelect
					label=""
					bind:value={criteriaToAdd}
					placeholder={availableCatalog.length > 0 ? "Add criterion…" : "All criteria added"}
					items={availableCatalog.map((entry) => ({ value: entry.attribute_name, name: entry.name }))}
					wrapperClass="w-56 mb-0"
					disabled={availableCatalog.length === 0}
				/>
				<AppButton variant="secondary" size="sm" onclick={addCriterion} disabled={!criteriaToAdd}>Add</AppButton>
			</div>

		</div>
		<div class="rounded-lg border border-cbase overflow-x-auto">
			<table class="w-full text-sm">
				<thead class="bg-secondary border-b border-cbase">
					<tr>
						<th class="px-4 py-2 text-left font-medium text-tsubtle whitespace-nowrap">Criterion</th>
						<th class="px-4 py-2 text-left font-medium text-tsubtle whitespace-nowrap">Type</th>
						<th class="px-4 py-2 text-left font-medium text-tsubtle whitespace-nowrap">Minimize</th>
						<th class="px-4 py-2"></th>
					</tr>
				</thead>
				<tbody class="divide-y divide-cbase">
					{#each selectedCriteria as criterion, criterionIndex}
						<tr class="hover:bg-secondary transition-colors">
							<td class="px-4 py-3 font-medium text-tdefault">{criterion.name}</td>
							<td class="px-4 py-3 text-tbody">{criterion.input_type}</td>
							<td class="px-4 py-3">
								<AppCheckbox bind:checked={selectedCriteria[criterionIndex].minimize} wrapperClass="" />
							</td>
							<td class="px-4 py-3 text-right">
								<AppButton variant="danger-secondary" size="sm" onclick={() => removeCriterion(criterion.attribute_name)}>Remove</AppButton>
							</td>
						</tr>
					{:else}
						<tr>
							<td colspan="4" class="px-4 py-10 text-center text-tbody">No criteria yet. Add one above or load a profile.</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<!-- AHP: pairwise comparison matrix -->
		{#if decisionMethod === "AHP" && selectedCriteria.length > 1}
			<div class="mt-4 rounded-lg border border-cbase bg-secondary p-4">
				<p class="text-sm font-medium text-tdefault mb-1">Pairwise Comparison Matrix</p>
				<p class="text-xs text-tsubtle mb-3">How much more important is the row criterion compared to the column criterion? (Saaty 1–9 scale)</p>
				<div class="overflow-x-auto">
					<table class="text-sm border-collapse">
						<thead>
							<tr>
								<th class="px-2 py-1"></th>
								{#each selectedCriteria.slice(1) as columnCriterion}
									<th class="px-3 py-1 text-center font-medium text-tsubtle whitespace-nowrap">{columnCriterion.name}</th>
								{/each}
							</tr>
						</thead>
						<tbody>
							{#each selectedCriteria.slice(0, -1) as rowCriterion, rowIndex}
								<tr>
									<td class="px-2 py-1 font-medium text-tdefault whitespace-nowrap pr-4">{rowCriterion.name}</td>
									{#each selectedCriteria as columnCriterion, columnIndex}
										{#if columnIndex > rowIndex}
											<td class="px-2 py-1">
												<AppSelect
													value={String(getPW(rowCriterion.attribute_name, columnCriterion.attribute_name))}
													items={SAATY_ITEMS}
													onchange={(value) => setPW(rowCriterion.attribute_name, columnCriterion.attribute_name, Number(value))}
													wrapperClass="w-48"
												/>
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

		<!-- TOPSIS / ELECTRE II: direct weights -->
		{#if (decisionMethod === "TOPSIS" || decisionMethod === "ELECTRE2") && selectedCriteria.length > 0}
			<div class="mt-4 rounded-lg border border-cbase bg-secondary p-4">
				<p class="text-sm font-medium text-tdefault mb-1">Criterion Weights</p>
				<p class="text-xs text-tsubtle mb-3">Enter a relative importance value for each criterion. Any positive numbers — they will be normalised to sum to 1 automatically.</p>
				<div class="flex flex-col gap-2">
					{#each selectedCriteria as criterion}
						{@const weightTotal = selectedCriteria.reduce((total, other) => total + getTW(other.attribute_name), 0)}
						<div class="flex items-center gap-3">
							<span class="text-sm text-tdefault w-52 truncate">{criterion.name}</span>
							<AppInput
								type="number" min="0.01" step="0.1"
								wrapperClass=""
								class="py-1 text-sm w-24 text-right"
								value={getTW(criterion.attribute_name)}
								onchange={(event) => setTW(criterion.attribute_name, Math.max(0.01, Number((event as Event & { currentTarget: HTMLInputElement }).currentTarget.value)))}
							/>
							<span class="text-xs text-tsubtle">{(getTW(criterion.attribute_name) / weightTotal * 100).toFixed(1)}%</span>
						</div>
					{/each}
				</div>
			</div>
		{/if}
	</div>

	<!-- Alternatives table -->
	<div>
		<div class="flex items-center justify-between mb-2">
			<h3 class="text-sm font-medium text-tdefault">Alternatives</h3>
			<AppButton variant="secondary" size="sm" onclick={addRow}>Add Row</AppButton>
		</div>
		<div class="rounded-lg border border-cbase overflow-x-auto">
			<table class="w-full text-sm">
				<thead class="bg-secondary border-b border-cbase">
					<tr>
						<th class="px-4 py-2 text-left font-medium text-tsubtle whitespace-nowrap">Name</th>
						<th class="px-4 py-2 text-left font-medium text-tsubtle whitespace-nowrap">Machines</th>
						<th class="px-4 py-2 text-left font-medium text-tsubtle whitespace-nowrap">Replacement (yrs)</th>
						{#each inputCriteria as criterion}
							<th class="px-4 py-2 text-left font-medium text-tsubtle whitespace-nowrap">{criterion.name}</th>
						{/each}
						<th class="px-4 py-2"></th>
					</tr>
				</thead>
				<tbody class="divide-y divide-cbase">
					{#each configs as config, rowIndex}
						<tr class="hover:bg-secondary transition-colors">
							<td class="px-4 py-2"><AppInput class="py-1 text-sm w-24" bind:value={config.name} wrapperClass="" /></td>
							<td class="px-4 py-2"><AppInput type="number" min="1" class="py-1 text-sm w-20" bind:value={config.machine_number} wrapperClass="" /></td>
							<td class="px-4 py-2"><AppInput type="number" min="1" class="py-1 text-sm w-20" bind:value={config.replacement_period} wrapperClass="" /></td>
							{#each inputCriteria as criterion}
								<td class="px-4 py-2">
									{#if criterion.input_type === "threshold_int"}
										<AppInput type="number" min="1" class="py-1 text-sm w-20" wrapperClass=""
											value={config.scores[criterion.attribute_name] ?? 36}
											oninput={(event) => { configs[rowIndex].scores[criterion.attribute_name] = parseInt(event.currentTarget.value) || 0; }} />
									{:else if criterion.input_type === "daily_hours"}
										<AppInput type="number" min="0" max="24" step="0.5" class="py-1 text-sm w-20" wrapperClass=""
											value={config.scores[criterion.attribute_name] ?? 24}
											oninput={(event) => { configs[rowIndex].scores[criterion.attribute_name] = parseFloat(event.currentTarget.value) || 0; }} />
									{:else}
										<AppInput type="number" min="0" max="10" step="0.5" class="py-1 text-sm w-20" wrapperClass=""
											value={config.scores[criterion.attribute_name] ?? 0}
											oninput={(event) => { configs[rowIndex].scores[criterion.attribute_name] = parseFloat(event.currentTarget.value) || 0; }} />
									{/if}
								</td>
							{/each}
							<td class="px-4 py-2 text-right">
								<AppButton variant="danger-secondary" size="sm" onclick={() => removeRow(rowIndex)}>Remove</AppButton>
							</td>
						</tr>
					{:else}
						<tr>
							<td colspan={inputCriteria.length + 4} class="px-4 py-10 text-center text-tbody">No alternatives yet. Add a row or load a profile.</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>

	<!-- Error -->
	{#if runError}
		<div class="rounded-lg border border-danger bg-danger/10 px-4 py-3 text-sm text-danger whitespace-pre-wrap">{runError}</div>
	{/if}

	{#if loadingRun}
		<p class="text-sm text-tbody">Loading saved run…</p>
	{/if}

	<!-- Results -->
	{#if result}
		<!-- Saved-run strip -->
		{#if savedRun}
			<div class="flex items-center justify-between gap-4 rounded-lg border border-cbase bg-secondary px-4 py-2.5 text-sm">
				<p class="text-tbody">
					{savedRun.reopened ? "Viewing saved run" : "Saved to History as"}
					<span class="font-medium text-tdefault">{savedRun.name}</span>
					<span class="text-tsubtle">· {fmtDateTime(savedRun.created_at)}</span>
					{#if savedRun.reopened}
						<span class="block text-xs text-tsubtle mt-0.5">Inputs above are restored from this run — change them and run again to create a new entry.</span>
					{/if}
				</p>
				<div class="flex gap-2 shrink-0">
					<AppButton onclick={exportPdf} loading={exportingPdf}>Export PDF</AppButton>
					<AppButton variant="secondary" onclick={() => goto("/history")}>Open History</AppButton>
				</div>
			</div>
		{/if}

		<!-- Tab bar -->
		<div class="border-b border-cbase">
			<nav class="flex gap-0 -mb-px">
				{#each visibleTabs as tab}
					<button
						onclick={() => (activeTab = tab.id)}
						class="px-4 py-2.5 text-sm border-b-2 transition-colors {activeTab === tab.id
							? 'border-brand text-brand font-medium'
							: 'border-transparent text-tsubtle hover:text-tdefault'}"
					>{tab.label}</button>
				{/each}
			</nav>
		</div>

		<!-- Ranking tab -->
		{#if activeTab === "ranking"}
			<!-- Consistency, weights and seed -->
			<div class="flex flex-wrap gap-x-6 gap-y-2 rounded-lg border border-cbase bg-secondary px-5 py-3 text-sm">
				{#if result.consistency_ratio >= 0}
					<div>
						<span class="text-tsubtle">Consistency Ratio</span>
						<span class="ml-2 font-medium {result.consistency_ratio < 0.1 ? 'text-tdefault' : 'text-danger'}">
							{(result.consistency_ratio * 100).toFixed(2)}%
							{result.consistency_ratio < 0.1 ? "✓" : "⚠ inconsistent"}
						</span>
					</div>
				{/if}
				{#each result.criteria_weights as criterionWeight}
					<div>
						<span class="text-tsubtle">{criterionWeight.name}</span>
						<span class="ml-1.5 font-medium text-tdefault">{(criterionWeight.weight * 100).toFixed(1)}%</span>
					</div>
				{/each}
				{#if lastSeedUsed != null}
					<div class="ml-auto">
						<span class="text-tsubtle">Seed</span>
						<span class="ml-1.5 font-medium text-tdefault">{lastSeedUsed}</span>
						{#if randomizeSeed}<span class="ml-1 text-xs text-tsubtle">(randomized)</span>{/if}
					</div>
				{/if}
			</div>

			{@const qualitativeCriteria = selectedCriteria.filter((criterion) => criterion.input_type === "qualitative")}
			<div class="rounded-lg border border-cbase overflow-x-auto">
				<table class="w-full text-sm">
					<thead class="bg-secondary border-b border-cbase">
						<tr>
							<th class="px-4 py-2 text-left font-medium text-tsubtle">Rank</th>
							<th class="px-4 py-2 text-left font-medium text-tsubtle">Alternative</th>
							<th class="px-4 py-2 text-left font-medium text-tsubtle">Machines</th>
							<th class="px-4 py-2 text-left font-medium text-tsubtle">Repl. (yrs)</th>
							<th class="px-4 py-2 text-right font-medium text-tsubtle">AHP Score</th>
							<th class="px-4 py-2 text-right font-medium text-tsubtle">Total Cost</th>
							<th class="px-4 py-2 text-right font-medium text-tsubtle">CM Cost</th>
							<th class="px-4 py-2 text-right font-medium text-tsubtle">PM Cost</th>
							<th class="px-4 py-2 text-right font-medium text-tsubtle">Purchase</th>
							{#if showNormalAvail}<th class="px-4 py-2 text-right font-medium text-tsubtle">Avail. Normal</th>{/if}
							{#if showCrisisAvail}<th class="px-4 py-2 text-right font-medium text-tsubtle">Avail. Crisis</th>{/if}
							{#if showNormalHours}<th class="px-4 py-2 text-right font-medium text-tsubtle">Availability - Normal</th>{/if}
							{#if showCrisisHours}<th class="px-4 py-2 text-right font-medium text-tsubtle">Availability - Crisis</th>{/if}
							{#each qualitativeCriteria as criterion}
								<th class="px-4 py-2 text-right font-medium text-tsubtle">{criterion.name}</th>
							{/each}
						</tr>
					</thead>
					<tbody class="divide-y divide-cbase">
						{#each result.alternatives as alternative}
							<tr class="hover:bg-secondary transition-colors {alternative.rank === 1 ? 'bg-brand-light' : ''}">
								<td class="px-4 py-3 font-semibold {alternative.rank === 1 ? 'text-brand' : 'text-tsubtle'}">#{alternative.rank}</td>
								<td class="px-4 py-3 font-medium text-tdefault">{alternative.name}</td>
								<td class="px-4 py-3 text-tbody">{alternative.machine_number}</td>
								<td class="px-4 py-3 text-tbody">{alternative.replacement_period}</td>
								<td class="px-4 py-3 text-right font-medium text-tdefault">{alternative.final_score.toFixed(4)}</td>
								<td class="px-4 py-3 text-right text-tbody">{eur(alternative.total_cost)}</td>
								<td class="px-4 py-3 text-right text-tbody">{eur(alternative.corrective_maintenance_cost)}</td>
								<td class="px-4 py-3 text-right text-tbody">{eur(alternative.preventive_maintenance_cost)}</td>
								<td class="px-4 py-3 text-right text-tbody">{eur(alternative.purchase_cost)}</td>
								{#if showNormalAvail}
									<td class="px-4 py-3 text-right text-tbody">{pct(alternative.normal_availability)}</td>
								{/if}
								{#if showCrisisAvail}
									<td class="px-4 py-3 text-right text-tbody">{pct(alternative.crisis_availability)}</td>
								{/if}
								{#if showNormalHours}<td class="px-4 py-3 text-right text-tbody">{hoursRatio(alternative.normal_hours_worked, alternative.normal_hours_scheduled)}</td>{/if}
								{#if showCrisisHours}<td class="px-4 py-3 text-right text-tbody">{hoursRatio(alternative.crisis_hours_worked, alternative.crisis_hours_scheduled)}</td>{/if}
								{#each qualitativeCriteria as criterion}
									<td class="px-4 py-3 text-right text-tbody">{alternative.scores[criterion.attribute_name] ?? "—"}</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}

		<!-- Event Timeline and Machines Available tabs: one alternative at a time -->
		{#if activeTab === "timeline" || activeTab === "availability"}
			{@const chartJson = activeTab === "timeline" ? currentCharts?.timeline_json : currentCharts?.availability_json}
			<div class="flex items-end justify-between gap-4">
				<p class="text-xs text-tsubtle">
					{#if chartAlternatives.length}
						First Monte Carlo replication of the selected alternative.
					{:else}
						First Monte Carlo replication of one alternative. This run was saved before charts could be shown per alternative.
					{/if}
				</p>
				{#if chartAlternatives.length}
					<AppSelect
						label="Alternative"
						bind:value={chartAlt}
						onchange={() => (chartError = null)}
						items={result.alternatives
							.filter((alternative) => chartAlternatives.includes(alternative.name))
							.map((alternative) => ({ value: alternative.name, name: `#${alternative.rank} ${alternative.name}` }))}
						wrapperClass="w-56 mb-0"
					/>
				{/if}
			</div>
			{#if chartError}
				<div class="rounded-lg border border-danger bg-danger/10 px-4 py-3 text-sm text-danger whitespace-pre-wrap">{chartError}</div>
			{:else if chartLoading && !chartJson}
				<p class="text-sm text-tbody">Drawing charts for {chartAlt}…</p>
			{:else if !chartJson}
				<p class="text-sm text-tsubtle">{activeTab === "timeline" ? "Timeline" : "Availability"} data not available.</p>
			{:else if activeTab === "timeline"}
				<div bind:this={timelineEl} class="w-full min-h-150"></div>
			{:else}
				<div bind:this={availabilityEl} class="w-full min-h-100"></div>
			{/if}
		{/if}

		<!-- AHP Details tab -->
		{#if activeTab === "ahp"}
			{@const sections = [
				{ title: "Decision Matrix (raw values)", rows: result.decision_matrix },
				{ title: "Normalized Scores", rows: result.normalized_scores },
				{ title: "Weighted Scores", rows: result.weighted_scores },
				{ title: "Criteria Pairwise Comparison Matrix", rows: result.pairwise_matrix },
			]}
			<div class="space-y-8">
				{#each sections as section}
					<div>
						<h4 class="text-sm font-semibold text-tdefault mb-2">{section.title}</h4>
						<div class="rounded-lg border border-cbase overflow-x-auto">
							<table class="w-full text-sm">
								<thead class="bg-secondary border-b border-cbase">
									<tr>
										<th class="px-4 py-2 text-left font-medium text-tsubtle"></th>
										{#each matrixColumns(section.rows) as column}
											<th class="px-4 py-2 text-right font-medium text-tsubtle whitespace-nowrap">{column}</th>
										{/each}
									</tr>
								</thead>
								<tbody class="divide-y divide-cbase">
									{#each section.rows as row}
										<tr class="hover:bg-secondary transition-colors">
											<td class="px-4 py-3 font-medium text-tdefault whitespace-nowrap">{row._row}</td>
											{#each matrixColumns(section.rows) as column}
												<td class="px-4 py-3 text-right text-tbody">{fmtCell(row[column])}</td>
											{/each}
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</div>
				{/each}
			</div>
		{/if}

		<!-- Sensitivity tab -->
		{#if activeTab === "sensitivity"}
			<div class="space-y-10">
				<!-- Criteria weights -->
				<div>
					<h4 class="text-sm font-semibold text-tdefault mb-1">Criteria weights</h4>
					<p class="text-xs text-tbody mb-2">
						One weight at a time is moved from 0 to 1 while the others are rescaled in proportion, and the
						alternatives are ranked again with the weighted sum.
					</p>
					{#if Object.keys(result.sensitivity_ranks ?? {}).length > 0}
						<div class="grid grid-cols-2 gap-x-6 gap-y-8">
							{#each Object.keys(result.sensitivity_ranks) as criterion}
								<div bind:this={sensitivityRankEls[criterion]} class="w-full"></div>
							{/each}
						</div>
					{:else}
						<p class="text-sm text-tsubtle">Weight sensitivity data not available.</p>
					{/if}
				</div>

				<!-- Total cost within its confidence interval -->
				<div>
					<h4 class="text-sm font-semibold text-tdefault mb-2">Total cost within its {ciLabel}</h4>
					{#if costCiRanking}
						{#if !costCiRanking.cost_is_criterion}
							<p class="text-xs text-tbody mb-2">Total cost is not a criterion in this run, so ranks cannot change.</p>
						{/if}
						<div class="grid grid-cols-2 gap-6 items-start">
							<div class="rounded-lg border border-cbase overflow-x-auto">
								<table class="w-full text-sm">
									<thead class="bg-secondary border-b border-cbase">
										<tr>
											<th class="px-4 py-2 text-left font-medium text-tsubtle">Alternative</th>
											<th class="px-4 py-2 text-right font-medium text-tsubtle whitespace-nowrap">Total cost</th>
											<th class="px-4 py-2 text-right font-medium text-tsubtle whitespace-nowrap">{ciLabel}</th>
											<th class="px-4 py-2 text-right font-medium text-tsubtle">Rank</th>
											<th class="px-4 py-2 text-right font-medium text-tsubtle whitespace-nowrap"
												title="Best: its total cost at the lower end of its interval, every other alternative's at the upper end. Worst: the reverse.">Rank range</th>
										</tr>
									</thead>
									<tbody class="divide-y divide-cbase">
										{#each result.alternatives as alternative}
											{@const entry = costCiRanking.alternatives.find((candidate) => candidate.name === alternative.name)}
											<tr class="hover:bg-secondary transition-colors">
												<td class="px-4 py-3 font-medium text-tdefault">{alternative.name}</td>
												<td class="px-4 py-3 text-right whitespace-nowrap text-tbody">{entry ? eur(entry.cost_mean) : "—"}</td>
												<td class="px-4 py-3 text-right whitespace-nowrap text-tbody">{entry ? `${eur(entry.ci_low)} – ${eur(entry.ci_high)}` : "—"}</td>
												<td class="px-4 py-3 text-right text-tbody">{entry?.rank_base ?? "—"}</td>
												<td class="px-4 py-3 text-right whitespace-nowrap {entry && entry.rank_best !== entry.rank_worst ? 'text-tdefault font-medium' : 'text-tbody'}">
													{entry ? rankRangeText(entry.rank_best, entry.rank_worst) : "—"}
												</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
							<div bind:this={costCiChartEl} class="w-full"></div>
						</div>
					{:else if !hasSpread}
						<p class="text-sm text-tsubtle">Needs at least 2 replications (no confidence interval).</p>
					{:else}
						<p class="text-sm text-tsubtle">Not available for this run (saved before this check existed). Run it again to see it.</p>
					{/if}
				</div>
			</div>
		{/if}

		<!-- Statistics & Report tab -->
		{#if activeTab === "statistics"}
			<div class="space-y-10">

				<!-- Summary and report download -->
				<div class="flex items-start justify-between gap-4 rounded-lg border border-cbase bg-secondary px-5 py-4">
					<div class="text-sm">
						<p class="font-medium text-tdefault">Monte Carlo statistics</p>
						<p class="text-tbody mt-0.5">
							{#if hasSpread}
								{replicationCount} replications per alternative · intervals are bootstrap percentile
								{ciLabel} on the mean (2,000 resamples of the replications) · convergence flagged when the relative half-width exceeds {REL_HW_FLAG * 100}%.
							{:else}
								{replicationCount} replication{replicationCount === 1 ? "" : "s"} per alternative. Confidence intervals, convergence and ranking
								robustness need at least 2 replications, so they are not shown.
							{/if}
						</p>
					</div>
					<AppButton onclick={downloadReport} loading={downloadingReport}>Download report (.xlsx)</AppButton>
				</div>

				<!-- Uncertainty table -->
				{#if result.statistics.length}
					{#if hasSpread}
					<div>
						<h4 class="text-sm font-semibold text-tdefault mb-2">Uncertainty — mean ± {ciLabel} half-width (relative half-width)</h4>
						<div class="rounded-lg border border-cbase overflow-x-auto">
							<table class="w-full text-sm">
								<thead class="bg-secondary border-b border-cbase">
									<tr>
										<th class="px-4 py-2 text-left font-medium text-tsubtle">Alternative</th>
										<th class="px-4 py-2 text-right font-medium text-tsubtle">N</th>
										{#each UNCERTAINTY_KEYS as metric}
											<th class="px-4 py-2 text-right font-medium text-tsubtle whitespace-nowrap">{METRIC_DEFS[metric].label}</th>
										{/each}
									</tr>
								</thead>
								<tbody class="divide-y divide-cbase">
									{#each result.statistics as alternativeStats}
										<tr class="hover:bg-secondary transition-colors">
											<td class="px-4 py-3 font-medium text-tdefault">{alternativeStats.name}</td>
											<td class="px-4 py-3 text-right text-tbody">{alternativeStats.n}</td>
											{#each UNCERTAINTY_KEYS as metric}
												{@const metricStats = alternativeStats.metrics[metric]}
												{@const flagged = metricStats.rel_half_width != null && metricStats.rel_half_width > REL_HW_FLAG}
												<td class="px-4 py-3 text-right whitespace-nowrap {flagged ? 'text-danger' : 'text-tbody'}">
													{fmtMetric(metric, metricStats.mean)}
													{#if metricStats.half_width != null}
														<span class="block text-xs text-tsubtle">{fmtHw(metric, metricStats.half_width)} ({fmtRel(metricStats.rel_half_width)})</span>
													{/if}
												</td>
											{/each}
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
						<p class="text-xs text-tsubtle mt-1.5">SD, SE and CI bounds for every metric are in the Excel report ("Uncertainty" sheet).</p>
					</div>
					{/if}

					<!-- Resilience -->
					<div>
						<h4 class="text-sm font-semibold text-tdefault mb-1">Resilience</h4>
						<p class="text-xs text-tbody mb-2">
							Expected unmet demand: average number of devices missing to reach the crisis target, following the fleet
							continuously and assuming crisis demand for the whole horizon{#if hasSpread} (mean ± {ciLabel} half-width){/if}.
						</p>
						<div class="w-fit max-w-full rounded-lg border border-cbase overflow-x-auto">
							<table class="text-sm">
								<thead class="bg-secondary border-b border-cbase">
									<tr>
										<th class="px-4 py-2 text-left font-medium text-tsubtle">Alternative</th>
										<th class="px-4 py-2 text-right font-medium text-tsubtle whitespace-nowrap">Expected unmet demand</th>
									</tr>
								</thead>
								<tbody class="divide-y divide-cbase">
									{#each result.alternatives as alternative}
										{@const unmet = statsByName.get(alternative.name)?.metrics.crisis_expected_unmet}
										<tr class="hover:bg-secondary transition-colors">
											<td class="px-4 py-3 font-medium text-tdefault">{alternative.name}</td>
											<td class="px-4 py-3 text-right whitespace-nowrap text-tbody">
												{fmtMetric("crisis_expected_unmet", unmet?.mean)}
												{#if unmet?.half_width != null}
													<span class="block text-xs text-tsubtle">{fmtHw("crisis_expected_unmet", unmet.half_width)}</span>
												{/if}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</div>

					<!-- Convergence -->
					{#if hasSpread}
					<div>
						<div class="flex items-end justify-between gap-4 mb-2">
							<h4 class="text-sm font-semibold text-tdefault">Convergence</h4>
							<div class="flex gap-3">
								<AppSelect
									label="Metric"
									bind:value={statMetric}
									items={METRIC_KEYS.map((metric) => ({ value: metric, name: metricLabel(metric) }))}
									wrapperClass="w-56 mb-0"
								/>
								<AppSelect
									label="Alternative (running mean)"
									bind:value={statAlt}
									items={result.statistics.map((alternativeStats) => ({ value: alternativeStats.name, name: alternativeStats.name }))}
									wrapperClass="w-56 mb-0"
								/>
							</div>
						</div>
						<div class="grid grid-cols-2 gap-4">
							<div bind:this={convMeanEl} class="w-full min-h-80"></div>
							<div bind:this={convRelEl} class="w-full min-h-80"></div>
						</div>

						<div class="rounded-lg border border-cbase overflow-x-auto mt-4">
							<table class="w-full text-sm">
								<thead class="bg-secondary border-b border-cbase">
									<tr>
										<th class="px-4 py-2 text-left font-medium text-tsubtle">Alternative</th>
										<th class="px-4 py-2 text-left font-medium text-tsubtle">Metric</th>
										<th class="px-4 py-2 text-right font-medium text-tsubtle">N run</th>
										<th class="px-4 py-2 text-right font-medium text-tsubtle whitespace-nowrap">Rel. half-width at N</th>
										<th class="px-4 py-2 text-right font-medium text-tsubtle whitespace-nowrap">N for ±5%</th>
										<th class="px-4 py-2 text-right font-medium text-tsubtle whitespace-nowrap">N for ±2%</th>
										<th class="px-4 py-2 text-right font-medium text-tsubtle whitespace-nowrap">N for ±1%</th>
									</tr>
								</thead>
								<tbody class="divide-y divide-cbase">
									{#each result.statistics as alternativeStats}
										{@const metricStats = alternativeStats.metrics[statMetric]}
										{@const flagged = metricStats.rel_half_width != null && metricStats.rel_half_width > REL_HW_FLAG}
										<tr class="hover:bg-secondary transition-colors">
											<td class="px-4 py-3 font-medium text-tdefault">{alternativeStats.name}</td>
											<td class="px-4 py-3 text-tbody">{metricLabel(statMetric)}</td>
											<td class="px-4 py-3 text-right text-tbody">{alternativeStats.n}</td>
											<td class="px-4 py-3 text-right {flagged ? 'text-danger font-medium' : 'text-tbody'}">{fmtRel(metricStats.rel_half_width)}{flagged ? " ⚠" : ""}</td>
											<td class="px-4 py-3 text-right text-tbody">{metricStats.n_required["0.05"] ?? "—"}</td>
											<td class="px-4 py-3 text-right text-tbody">{metricStats.n_required["0.02"] ?? "—"}</td>
											<td class="px-4 py-3 text-right text-tbody">{metricStats.n_required["0.01"] ?? "—"}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
						<p class="text-xs text-tsubtle mt-1.5">"N for ±x%" is the replication count at which the {ciLabel} half-width would fall to x% of the mean, scaling the current half-width by 1/√N.</p>
					</div>
					{/if}
				{/if}

				<!-- Rank robustness -->
				{#if hasSpread}
				<div>
					<h4 class="text-sm font-semibold text-tdefault mb-2">Ranking robustness (bootstrap)</h4>
					{#if result.bootstrap}
						{@const rankCount = result.bootstrap.alternatives.length}
						<p class="text-xs text-tbody mb-2">
							{result.bootstrap.samples} resamples of the {result.bootstrap.replications_per_alternative} replications per alternative,
							re-ranked with {result.bootstrap.method}
							{#if result.bootstrap.held_constant.length}· held constant: {result.bootstrap.held_constant.join(", ")}{/if}.
						</p>
						<div class="rounded-lg border border-cbase overflow-x-auto">
							<table class="w-full text-sm">
								<thead class="bg-secondary border-b border-cbase">
									<tr>
										<th class="px-4 py-2 text-left font-medium text-tsubtle">Alternative</th>
										<th class="px-4 py-2 text-right font-medium text-tsubtle">P(rank 1)</th>
										<th class="px-4 py-2 text-right font-medium text-tsubtle">Mean rank</th>
										<th class="px-4 py-2 text-right font-medium text-tsubtle whitespace-nowrap">{ciLabel.replace(" CI", "")} rank interval</th>
										{#each Array(rankCount) as _, rankIndex}
											<th class="px-2 py-2 text-center font-medium text-tsubtle">#{rankIndex + 1}</th>
										{/each}
									</tr>
								</thead>
								<tbody class="divide-y divide-cbase">
									{#each bootstrapSorted as bootstrapResult}
										<tr class="hover:bg-secondary transition-colors">
											<td class="px-4 py-3 font-medium text-tdefault">{bootstrapResult.name}</td>
											<td class="px-4 py-3 text-right text-tbody">{(bootstrapResult.p_best * 100).toFixed(1)}%</td>
											<td class="px-4 py-3 text-right text-tbody">{bootstrapResult.mean_rank.toFixed(2)}</td>
											<td class="px-4 py-3 text-right text-tbody">{bootstrapResult.rank_ci[0]}–{bootstrapResult.rank_ci[1]}</td>
											{#each bootstrapResult.rank_probabilities as probability}
												<td class="px-2 py-3 text-center text-xs {rankCellClass(probability)}">
													{probability > 0 ? (probability * 100).toFixed(0) + "%" : "·"}
												</td>
											{/each}
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					{:else}
						<p class="text-sm text-tsubtle">Bootstrap not run (bootstrap draws set to 0).</p>
					{/if}
				</div>
				{/if}

				<!-- Parameter table -->
				{#if result.parameter_table?.run}
					{@const parameterTable = result.parameter_table}
					<div class="space-y-6">
						<h4 class="text-sm font-semibold text-tdefault">Parameter table</h4>

						<div>
							<h5 class="text-xs font-semibold uppercase tracking-wide text-tsubtle mb-1.5">Run</h5>
							<div class="w-fit max-w-full rounded-lg border border-cbase overflow-x-auto">
								<table class="text-sm">
									<tbody class="divide-y divide-cbase">
										{#each Object.entries(parameterTable.run) as [settingName, settingValue]}
											<tr class="hover:bg-secondary transition-colors"><td class="px-4 py-3 font-medium text-tdefault whitespace-nowrap">{settingName}</td><td class="px-4 py-3 text-tbody">{cellText(settingValue)}</td></tr>
										{/each}
									</tbody>
								</table>
							</div>
						</div>

						{#each [
							{ title: "Alternatives", rows: paramAlternativeRows },
							{ title: "Fleet (machine cohorts loaded)", rows: parameterTable.fleet ?? [] },
							{ title: "Spare parts", rows: parameterTable.spare_parts ?? [] },
							{ title: "Cost profiles", rows: parameterTable.cost_profiles ?? [] },
							{ title: "Preventive maintenance programmes", rows: paramPmRows },
							{ title: "Decision criteria & weights", rows: parameterTable.decision?.criteria ?? [] },
						] as section}
							<div>
								<h5 class="text-xs font-semibold uppercase tracking-wide text-tsubtle mb-1.5">{section.title}</h5>
								{#if section.rows.length}
									<div class="rounded-lg border border-cbase overflow-x-auto">
										<table class="w-full text-sm">
											<thead class="bg-secondary border-b border-cbase">
												<tr>
													{#each rowKeys(section.rows) as columnName}
														<th class="px-4 py-2 text-left font-medium text-tsubtle whitespace-nowrap">{columnName}</th>
													{/each}
												</tr>
											</thead>
											<tbody class="divide-y divide-cbase">
												{#each section.rows as row}
													<tr class="hover:bg-secondary transition-colors">
														{#each rowKeys(section.rows) as columnName}
															<td class="px-4 py-3 text-tbody whitespace-nowrap">{cellText(row[columnName])}</td>
														{/each}
													</tr>
												{/each}
											</tbody>
										</table>
									</div>
								{:else}
									<p class="text-xs text-tsubtle">— none —</p>
								{/if}
							</div>
						{/each}

						<div>
							<h5 class="text-xs font-semibold uppercase tracking-wide text-tsubtle mb-1.5">Decision method</h5>
							<div class="w-fit max-w-full rounded-lg border border-cbase overflow-x-auto">
								<table class="text-sm">
									<tbody class="divide-y divide-cbase">
										<tr class="hover:bg-secondary transition-colors"><td class="px-4 py-3 font-medium text-tdefault">method</td><td class="px-4 py-3 text-tbody">{parameterTable.decision?.method}</td></tr>
										{#if parameterTable.decision?.consistency_ratio != null}
											<tr class="hover:bg-secondary transition-colors"><td class="px-4 py-3 font-medium text-tdefault">consistency_ratio</td><td class="px-4 py-3 text-tbody">{cellText(parameterTable.decision.consistency_ratio)}</td></tr>
										{/if}
										{#if parameterTable.decision?.lambda_max != null}
											<tr class="hover:bg-secondary transition-colors"><td class="px-4 py-3 font-medium text-tdefault">λmax</td><td class="px-4 py-3 text-tbody">{cellText(parameterTable.decision.lambda_max)}</td></tr>
										{/if}
										{#if parameterTable.decision?.random_index != null}
											<tr class="hover:bg-secondary transition-colors"><td class="px-4 py-3 font-medium text-tdefault">RI (random index)</td><td class="px-4 py-3 text-tbody">{cellText(parameterTable.decision.random_index)}</td></tr>
										{/if}
										{#if parameterTable.decision?.ahp_weight_derivation}
											<tr class="hover:bg-secondary transition-colors"><td class="px-4 py-3 font-medium text-tdefault">ahp_weight_derivation</td><td class="px-4 py-3 text-tbody">{parameterTable.decision.ahp_weight_derivation}</td></tr>
										{/if}
										{#if parameterTable.decision?.electre2}
											{#each Object.entries(parameterTable.decision.electre2) as [settingName, settingValue]}
												<tr class="hover:bg-secondary transition-colors"><td class="px-4 py-3 font-medium text-tdefault">electre2.{settingName}</td><td class="px-4 py-3 text-tbody">{cellText(settingValue)}</td></tr>
											{/each}
										{/if}
										{#if parameterTable.decision?.direct_weights}
											<tr class="hover:bg-secondary transition-colors"><td class="px-4 py-3 font-medium text-tdefault">direct_weights</td><td class="px-4 py-3 text-tbody">{cellText(parameterTable.decision.direct_weights)}</td></tr>
										{/if}
									</tbody>
								</table>
							</div>
							{#if parameterTable.decision?.pairwise_matrix}
								{@const pairwise = parameterTable.decision.pairwise_matrix}
								<div class="w-fit max-w-full rounded-lg border border-cbase overflow-x-auto mt-3">
									<table class="text-sm">
										<thead class="bg-secondary border-b border-cbase">
											<tr>
												<th class="px-4 py-2 text-left font-medium text-tsubtle">Pairwise (row vs column)</th>
												{#each pairwise.criteria as criterionName}<th class="px-4 py-2 text-right font-medium text-tsubtle whitespace-nowrap">{criterionName}</th>{/each}
											</tr>
										</thead>
										<tbody class="divide-y divide-cbase">
											{#each pairwise.rows as row, rowIndex}
												<tr class="hover:bg-secondary transition-colors">
													<td class="px-4 py-3 font-medium text-tdefault whitespace-nowrap">{pairwise.criteria[rowIndex]}</td>
													{#each row as value}<td class="px-4 py-3 text-right text-tbody">{cellText(value)}</td>{/each}
												</tr>
											{/each}
										</tbody>
									</table>
								</div>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		{/if}
	{/if}

</div>

<!-- Load Profile modal -->
<AppModal bind:open={profileModalOpen} title="Load Scenario Profile" size="screen">
	{#if profilesLoading}
		<p class="text-sm text-tbody">Loading profiles…</p>
	{:else if profiles.length === 0}
		<p class="text-sm text-tbody">No saved profiles yet. Create one in the <a href="/scenarios" class="text-brand underline">Scenarios</a> page.</p>
	{:else}
		<div class="divide-y divide-cbase rounded-lg border border-cbase overflow-hidden">
			{#each profiles as profile}
				<button
					onclick={() => applyProfile(profile)}
					class="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-secondary transition-colors"
				>
					<div>
						<p class="text-sm font-medium text-tdefault">{profile.name}</p>
						<p class="text-xs text-tbody mt-0.5">{profile.config.criteria.length} criteria · {profile.config.alternatives.length} alternatives</p>
					</div>
					<svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4 text-tsubtle" fill="none" viewBox="0 0 24 24" stroke="currentColor">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
					</svg>
				</button>
			{/each}
		</div>
	{/if}
</AppModal>
