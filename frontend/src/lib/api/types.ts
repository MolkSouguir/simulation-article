export type MachineType = string;

export interface MachineTypeRecord {
	id: string;
	name: string;
}

export type MachineTypeCreate = Omit<MachineTypeRecord, "id">;
export type MachineTypeUpdate = Partial<MachineTypeCreate>;
export type MachineStatus = "active" | "standby" | "maintenance";
export type SparePartType =
	| "sensor"
	| "filter"
	| "battery"
	| "gasket"
	| "valve"
	| "roulement"
	| "kit constructor";
export type SparePartStatus = "used" | "new";

export interface SparePartSummary {
	id: string;
	name: string;
	code: string;
}

export interface Machine {
	id: string;
	name: string;
	code: string;
	machine_type: MachineType;
	purchase_year: number;
	purchase_cost: number;
	status: MachineStatus;
	eta: number;
	beta: number;
	maintenance_cost_data_id: string | null;
	preventive_maintenance_id: string | null;
	spare_parts: SparePartSummary[];
}

export type MachineCreate = Omit<Machine, "id" | "spare_parts">;
export type MachineUpdate = Partial<MachineCreate>;

export interface SparePart {
	id: string;
	name: string;
	code: string;
	spare_part_type: SparePartType;
	purchase_year: number;
	purchase_cost: number;
	status: SparePartStatus;
	eta: number;
	beta: number;
	machine_id: string | null;
	maintenance_cost_data_id: string | null;
}

export type SparePartCreate = Omit<SparePart, "id">;
export type SparePartUpdate = Partial<SparePartCreate>;

export interface MaintenanceCostData {
	id: string;
	name: string;
	hourly_labor_cost: number;
	corrective_maintenance_hours: number;
	corrective_maintenance_additional_downtime_hours: number;
	preventive_maintenance_hours: number;
}

export type MaintenanceCostDataCreate = Omit<MaintenanceCostData, "id">;
export type MaintenanceCostDataUpdate = Partial<MaintenanceCostDataCreate>;

export interface PMCycleYearPart {
	id: string;
	spare_part_type: SparePartType;
}

export interface PMCycleYear {
	id: string;
	order: number;
	preventive_maintenance_hours: number;
	hourly_labor_cost: number;
	pm_year_cost: number;
	parts: PMCycleYearPart[];
}

export interface PreventiveMaintenance {
	id: string;
	name: string;
	years_interval: number;
	cycle_years: PMCycleYear[];
}

export type PreventiveMaintenanceCreate = Omit<PreventiveMaintenance, "id" | "cycle_years"> & {
	cycle_years: Array<{
		order: number;
		preventive_maintenance_hours: number;
		hourly_labor_cost: number;
		pm_year_cost: number;
		parts: SparePartType[];
	}>;
};
export type PreventiveMaintenanceUpdate = Partial<Pick<PreventiveMaintenance, "name" | "years_interval">>;

export interface PMCycleYearCreate {
	order: number;
	preventive_maintenance_hours: number;
	hourly_labor_cost: number;
	pm_year_cost: number;
	parts: SparePartType[];
}

export type PMCycleYearUpdate = Partial<PMCycleYearCreate>;

export interface ScenarioCriterion {
	attribute_name: string;
	name: string;
	input_type: "threshold_int" | "computed" | "qualitative" | "daily_hours";
	minimize: boolean;
}

export interface ScenarioAlternative {
	name: string;
	machine_number: number;
	replacement_period: number;
	scores: Record<string, number>;
}

export type DecisionMethod = "AHP" | "TOPSIS" | "ELECTRE" | "ELECTRE2";

export interface SimulationBehavior {
	session_days: number[];
	shift_durations: number[];
	machine_type: string;
}

export const DEFAULT_SIMULATION_BEHAVIOR: SimulationBehavior = {
	session_days: [0, 1, 2, 3, 4, 5, 6],
	shift_durations: [24],
	machine_type: "ventilator",
};

export interface ScenarioConfig {
	method: DecisionMethod;
	simulation: SimulationBehavior;
	criteria: ScenarioCriterion[];
	alternatives: ScenarioAlternative[];
	pairwise_upper_triangle?: number[];  // AHP
	direct_weights?: number[];           // TOPSIS and ELECTRE II
}

export interface ScenarioProfile {
	id: string;
	name: string;
	config: ScenarioConfig;
}

export type ScenarioProfileCreate = Omit<ScenarioProfile, "id">;
export type ScenarioProfileUpdate = Partial<ScenarioProfileCreate>;

// Saved simulation runs, listed on the History page

export interface SimulationRunSummary {
	id: string;
	name: string;
	created_at: string;          // ISO date in UTC
	method: string;
	machine_type: string;
	alternative_count: number;
	simulation_number: number;
	period: number;
	seed: number;
	best_alternative: string | null;
}

export interface SimulationRun extends SimulationRunSummary {
	request: Record<string, any>;  // what was sent to /simulation/run
	result: Record<string, any>;   // what came back (the Simulation page has the full type)
}

export type SimulationRunUpdate = Partial<Pick<SimulationRunSummary, "name">>;

// Ranks with every total cost anywhere in its confidence interval
// (analysis/statistics.py cost_ci_ranking)
export interface CostCiRankingAlternative {
	name: string;
	cost_mean: number;
	ci_low: number;
	ci_high: number;
	rank_base: number;   // with the mean costs
	rank_best: number;   // its cost at ci_low, the others' at ci_high
	rank_worst: number;  // its cost at ci_high, the others' at ci_low
}
export interface CostCiRankingSummary {
	confidence_level: number;
	cost_is_criterion: boolean;
	alternatives: CostCiRankingAlternative[];
}

// Timeline and availability charts (Plotly JSON) of one alternative of a saved run
export interface SimulationRunCharts {
	alternative: string;
	timeline_json: string | null;
	availability_json: string | null;
}
