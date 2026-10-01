export * from "./types";
import { api } from "./client";
import type {
	MachineTypeRecord, MachineTypeCreate, MachineTypeUpdate,
	Machine, MachineCreate, MachineUpdate,
	SparePart, SparePartCreate, SparePartUpdate,
	MaintenanceCostData, MaintenanceCostDataCreate, MaintenanceCostDataUpdate,
	PreventiveMaintenance, PreventiveMaintenanceCreate, PreventiveMaintenanceUpdate,
	PMCycleYear, PMCycleYearCreate, PMCycleYearUpdate,
	ScenarioProfile, ScenarioProfileCreate, ScenarioProfileUpdate,
	SimulationRun, SimulationRunSummary, SimulationRunUpdate, SimulationRunCharts,
} from "./types";

export const machineTypesApi = {
	list: () => api.get<MachineTypeRecord[]>("/machine-types/"),
	create: (body: MachineTypeCreate) => api.post<MachineTypeRecord>("/machine-types/", body),
	update: (id: string, body: MachineTypeUpdate) => api.patch<MachineTypeRecord>(`/machine-types/${id}`, body),
	delete: (id: string) => api.delete(`/machine-types/${id}`),
};

export const machinesApi = {
	list: () => api.get<Machine[]>("/machines/"),
	get: (id: string) => api.get<Machine>(`/machines/${id}`),
	create: (body: MachineCreate) => api.post<Machine>("/machines/", body),
	update: (id: string, body: MachineUpdate) => api.patch<Machine>(`/machines/${id}`, body),
	delete: (id: string) => api.delete(`/machines/${id}`),
};

export const sparePartsApi = {
	list: (machineId?: string) =>
		api.get<SparePart[]>(`/spare-parts/${machineId != null ? `?machine_id=${machineId}` : ""}`),
	get: (id: string) => api.get<SparePart>(`/spare-parts/${id}`),
	create: (body: SparePartCreate) => api.post<SparePart>("/spare-parts/", body),
	update: (id: string, body: SparePartUpdate) => api.patch<SparePart>(`/spare-parts/${id}`, body),
	delete: (id: string) => api.delete(`/spare-parts/${id}`),
};

export const costProfilesApi = {
	list: () => api.get<MaintenanceCostData[]>("/cost-profiles/"),
	get: (id: string) => api.get<MaintenanceCostData>(`/cost-profiles/${id}`),
	create: (body: MaintenanceCostDataCreate) => api.post<MaintenanceCostData>("/cost-profiles/", body),
	update: (id: string, body: MaintenanceCostDataUpdate) =>
		api.patch<MaintenanceCostData>(`/cost-profiles/${id}`, body),
	delete: (id: string) => api.delete(`/cost-profiles/${id}`),
};

export const pmCycleYearsApi = {
	create: (pmId: string, body: PMCycleYearCreate) =>
		api.post<PMCycleYear>(`/preventive-maintenance/${pmId}/cycle-years/`, body),
	update: (pmId: string, cyId: string, body: PMCycleYearUpdate) =>
		api.patch<PMCycleYear>(`/preventive-maintenance/${pmId}/cycle-years/${cyId}`, body),
	delete: (pmId: string, cyId: string) =>
		api.delete(`/preventive-maintenance/${pmId}/cycle-years/${cyId}`),
};

export const pmApi = {
	list: () => api.get<PreventiveMaintenance[]>("/preventive-maintenance/"),
	get: (id: string) => api.get<PreventiveMaintenance>(`/preventive-maintenance/${id}`),
	create: (body: PreventiveMaintenanceCreate) =>
		api.post<PreventiveMaintenance>("/preventive-maintenance/", body),
	update: (id: string, body: PreventiveMaintenanceUpdate) =>
		api.patch<PreventiveMaintenance>(`/preventive-maintenance/${id}`, body),
	delete: (id: string) => api.delete(`/preventive-maintenance/${id}`),
};

export const scenarioProfilesApi = {
	list: () => api.get<ScenarioProfile[]>("/scenario-profiles/"),
	get: (id: string) => api.get<ScenarioProfile>(`/scenario-profiles/${id}`),
	create: (body: ScenarioProfileCreate) => api.post<ScenarioProfile>("/scenario-profiles/", body),
	update: (id: string, body: ScenarioProfileUpdate) => api.patch<ScenarioProfile>(`/scenario-profiles/${id}`, body),
	delete: (id: string) => api.delete(`/scenario-profiles/${id}`),
};

export const simulationRunsApi = {
	list: () => api.get<SimulationRunSummary[]>("/simulation-runs/"),
	get: (id: string) => api.get<SimulationRun>(`/simulation-runs/${id}`),
	update: (id: string, body: SimulationRunUpdate) => api.patch<SimulationRunSummary>(`/simulation-runs/${id}`, body),
	delete: (id: string) => api.delete(`/simulation-runs/${id}`),
	charts: (id: string, alternative: string) =>
		api.get<SimulationRunCharts>(`/simulation-runs/${id}/charts?alternative=${encodeURIComponent(alternative)}`),
	downloadPdf: (id: string) => api.download(`/simulation-runs/${id}/pdf`, "simulation_run.pdf"),
};
